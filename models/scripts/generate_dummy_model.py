#!/usr/bin/env python3
"""
Script to generate a lightweight valid ONNX model for Triton Inference Server.
Model computes: OUTPUT_0 = Softmax(INPUT_0 * W + B)
Input: [batch, 128] FP32
Output: [batch, 2] FP32
"""

import os
import sys

def generate_model(output_path: str, model_name: str = "sentiment_classifier", feature_dim: int = 128, num_classes: int = 2):
    try:
        import onnx
        from onnx import helper, TensorProto
        import numpy as np
    except ImportError:
        print(f"[INFO] ONNX library not found. Creating placeholder model marker for {model_name}.")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(f"ONNX_PLACEHOLDER_{model_name.upper()}".encode("utf-8"))
        print(f"[OK] Created placeholder at {output_path}")
        return

    print(f"[INFO] Generating ONNX model '{model_name}' (dim={feature_dim}) at {output_path}...")

    # Weights and Biases
    w_val = np.random.randn(feature_dim, num_classes).astype(np.float32) * 0.1
    b_val = np.zeros((num_classes,), dtype=np.float32)

    # Inputs and Outputs
    input_tensor = helper.make_tensor_value_info("INPUT_0", TensorProto.FLOAT, [-1, feature_dim])
    output_tensor = helper.make_tensor_value_info("OUTPUT_0", TensorProto.FLOAT, [-1, num_classes])

    # Initializers (constants)
    w_init = helper.make_tensor("W", TensorProto.FLOAT, [feature_dim, num_classes], w_val.flatten().tolist())
    b_init = helper.make_tensor("B", TensorProto.FLOAT, [num_classes], b_val.flatten().tolist())

    # Nodes: MatMul -> Add -> Softmax
    matmul_node = helper.make_node("MatMul", ["INPUT_0", "W"], ["matmul_out"])
    add_node = helper.make_node("Add", ["matmul_out", "B"], ["logits"])
    softmax_node = helper.make_node("Softmax", ["logits"], ["OUTPUT_0"], axis=1)

    # Graph
    graph = helper.make_graph(
        [matmul_node, add_node, softmax_node],
        model_name,
        [input_tensor],
        [output_tensor],
        [w_init, b_init],
    )

    model = helper.make_model(graph, producer_name="kubescale-ai")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    onnx.save(model, output_path)
    print(f"[SUCCESS] ONNX model '{model_name}' saved to {output_path}")


if __name__ == "__main__":
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # Generate sentiment_onnx
    sentiment_path = os.path.join(base_dir, "sentiment_onnx", "1", "model.onnx")
    generate_model(sentiment_path, "sentiment_onnx", feature_dim=128, num_classes=2)
    
    # Generate fraud_detection_onnx
    fraud_path = os.path.join(base_dir, "fraud_detection_onnx", "1", "model.onnx")
    generate_model(fraud_path, "fraud_detection_onnx", feature_dim=64, num_classes=2)


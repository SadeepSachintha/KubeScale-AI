# ==============================================================================
# IAM Roles for Service Accounts (IRSA) & S3 Model Storage
# ==============================================================================

# ------------------------------------------------------------------------------
# EKS Cluster OIDC Identity Provider
# ------------------------------------------------------------------------------
data "tls_certificate" "eks" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer

  tags = var.tags
}

# ------------------------------------------------------------------------------
# S3 Model Repository Bucket
# ------------------------------------------------------------------------------
resource "aws_s3_bucket" "model_repository" {
  bucket = var.model_storage_bucket_name

  tags = merge(
    var.tags,
    {
      Name        = var.model_storage_bucket_name
      Description = "Triton Inference Server Model Repository"
    }
  )
}

resource "aws_s3_bucket_versioning" "model_repository" {
  bucket = aws_s3_bucket.model_repository.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "model_repository" {
  bucket = aws_s3_bucket.model_repository.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "model_repository" {
  bucket = aws_s3_bucket.model_repository.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ------------------------------------------------------------------------------
# IRSA Role for Model Inference Pods (Triton / ONNX)
# ------------------------------------------------------------------------------
data "aws_iam_policy_document" "inference_irsa_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:${var.inference_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "inference_s3_access" {
  name               = "${var.project_name}-inference-s3-irsa-role"
  assume_role_policy = data.aws_iam_policy_document.inference_irsa_assume_role.json

  tags = var.tags
}

# Least-privilege IAM policy allowing only read and list actions on model repository
resource "aws_iam_policy" "inference_s3_read_only" {
  name        = "${var.project_name}-inference-s3-readonly"
  description = "Allows Triton inference pods to read model weights from S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListModelBucket"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = aws_s3_bucket.model_repository.arn
      },
      {
        Sid    = "ReadModelArtifacts"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = "${aws_s3_bucket.model_repository.arn}/*"
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "inference_s3_attach" {
  role       = aws_iam_role.inference_s3_access.name
  policy_arn = aws_iam_policy.inference_s3_read_only.policy_arn
}

# ------------------------------------------------------------------------------
# IRSA Role for External Secrets Operator (AWS Secrets Manager)
# ------------------------------------------------------------------------------
data "aws_iam_policy_document" "eso_irsa_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:kubescale-eso-sa"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eso_secrets_access" {
  name               = "${var.project_name}-eso-irsa-role"
  assume_role_policy = data.aws_iam_policy_document.eso_irsa_assume_role.json

  tags = var.tags
}

resource "aws_iam_policy" "eso_secrets_read" {
  name        = "${var.project_name}-eso-secrets-readonly"
  description = "Allows External Secrets Operator to read secrets from AWS Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:kubescale/*"
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "eso_secrets_attach" {
  role       = aws_iam_role.eso_secrets_access.name
  policy_arn = aws_iam_policy.eso_secrets_read.policy_arn
}


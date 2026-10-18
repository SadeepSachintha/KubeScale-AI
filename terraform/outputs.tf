output "vpc_id" {
  description = "The ID of the custom VPC"
  value       = aws_vpc.this.id
}

output "public_subnets" {
  description = "List of IDs of public subnets"
  value       = aws_subnet.public[*].id
}

output "private_subnets" {
  description = "List of IDs of private subnets"
  value       = aws_subnet.private[*].id
}

output "cluster_name" {
  description = "The name of the EKS cluster"
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "Endpoint URL for Amazon EKS control plane API"
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 encoded certificate data required to communicate with the cluster"
  value       = aws_eks_cluster.this.certificate_authority[0].data
  sensitive   = true
}

output "cluster_security_group_id" {
  description = "Security group ID attached to the EKS control plane"
  value       = aws_security_group.cluster.id
}

output "oidc_provider_arn" {
  description = "ARN of the OIDC Provider for EKS IRSA"
  value       = aws_iam_openid_connect_provider.eks.arn
}

output "inference_irsa_role_arn" {
  description = "IAM Role ARN for Triton Inference Pods IRSA service account"
  value       = aws_iam_role.inference_s3_access.arn
}

output "model_repository_bucket" {
  description = "S3 Bucket name housing Triton model repository"
  value       = aws_s3_bucket.model_repository.id
}

output "eso_irsa_role_arn" {
  description = "IAM Role ARN for External Secrets Operator IRSA service account"
  value       = aws_iam_role.eso_secrets_access.arn
}

output "kubectl_config_command" {
  description = "Command to update local kubeconfig with the provisioned EKS cluster"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${aws_eks_cluster.this.name}"
}


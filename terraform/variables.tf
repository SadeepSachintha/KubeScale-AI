variable "aws_region" {
  description = "AWS region where resources will be provisioned"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name identifier for resource naming and tagging"
  type        = string
  default     = "kubescale"
}

variable "cluster_name" {
  description = "Name of the Amazon EKS cluster"
  type        = string
  default     = "kubescale-ai-cluster"
}

variable "cluster_version" {
  description = "Kubernetes control plane version"
  type        = string
  default     = "1.30"
}

variable "vpc_cidr" {
  description = "CIDR block for the custom VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of Availability Zones to deploy subnets into"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (worker nodes & workloads)"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24", "10.0.12.0/24"]
}

variable "single_nat_gateway" {
  description = "Provision a single NAT Gateway for cost reduction in non-production environments"
  type        = bool
  default     = true
}

variable "node_group_instance_types" {
  description = "EC2 instance types for EKS managed node group"
  type        = list(string)
  default     = ["t3.xlarge"]
}

variable "node_group_min_size" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 2
}

variable "node_group_max_size" {
  description = "Maximum number of worker nodes (auto-scaling limit)"
  type        = number
  default     = 10
}

variable "node_group_desired_size" {
  description = "Desired number of worker nodes at initial launch"
  type        = number
  default     = 3
}

variable "model_storage_bucket_name" {
  description = "Name of the S3 bucket housing Triton model repository"
  type        = string
  default     = "kubescale-ai-model-repository"
}

variable "k8s_namespace" {
  description = "Kubernetes namespace for application deployment"
  type        = string
  default     = "kubescale"
}

variable "inference_service_account" {
  description = "Kubernetes ServiceAccount name for Triton inference server IRSA"
  type        = string
  default     = "kubescale-inference-sa"
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
  default = {
    Project     = "KubeScale-AI"
    ManagedBy   = "Terraform"
    Environment = "dev"
  }
}

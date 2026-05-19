output "cluster_id" {
  description = "ROSA HCP Cluster ID"
  value       = module.cluster.cluster_id
}

output "cluster_name" {
  value = var.cluster_name
}

output "api_url" {
  value = module.cluster.api_url
}

output "console_url" {
  value = module.cluster.console_url
}

output "vpc_id" {
  value = local.network.vpc_id
}

output "region" {
  value = var.region
}

output "private_subnet_ids" {
  value = local.network.private_subnet_ids
}

output "public_subnet_ids" {
  value = local.network.public_subnet_ids
}

output "identity_provider_id" {
  value = module.cluster.identity_provider_id
}

output "admin_password_secret_arn" {
  description = "Secrets Manager ARN for admin password (retrieve with get-secret-value)."
  value       = aws_secretsmanager_secret.admin_password.arn
}

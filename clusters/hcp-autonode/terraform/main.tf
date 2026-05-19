# ROSA HCP AutoNode — Terraform stack for clusters/hcp-autonode/.
# Separate from clusters/hcp/terraform/ so AutoNode-specific settings (provision_shard_id
# via additional_cluster_properties, single-AZ fixed replicas) don't pollute the base HCP stack.
# All three Git module sources MUST use the same ref string (Terraform does not allow variable interpolation in source).
# Pinned to 28b2933 — "feat(cluster): add additional_cluster_properties variable":
# adds additional_cluster_properties (map(string)) merged last into rhcs_cluster_rosa_hcp properties block,
# enabling injection of provision_shard_id for the AutoNode private preview.
# Previous pin d6ae385 fixed the CLUSTERS-MGMT-403 race (per-pool vs total replicas); that fix is included here.

resource "random_id" "resource_suffix" {
  byte_length = 4
  keepers = {
    cluster_name = var.cluster_name
  }
  lifecycle {
    create_before_destroy = false
  }
}

resource "random_password" "admin_password" {
  length           = 20
  special          = true
  upper            = true
  lower            = true
  numeric          = true
  override_special = "@#&*-_"
}

module "network_public" {
  source = "git::https://github.com/rh-mobb/validated-pattern-terraform-rosa.git//modules/infrastructure/network-public?ref=28b293329af938f1f7b5662e7223831eee0df506"

  name_prefix                    = var.cluster_name
  vpc_cidr                       = var.vpc_cidr
  multi_az                       = var.multi_az
  tags                           = local.tags
  persists_through_sleep         = var.persists_through_sleep
  persists_through_sleep_network = var.persists_through_sleep_network
}

locals {
  network = {
    vpc_id               = module.network_public.vpc_id
    vpc_cidr_block       = module.network_public.vpc_cidr_block
    private_subnet_ids   = tolist(module.network_public.private_subnet_ids)
    public_subnet_ids    = tolist(module.network_public.public_subnet_ids)
    private_subnet_azs   = tolist(module.network_public.private_subnet_azs)
    private_subnet_cidrs = tolist(module.network_public.private_subnet_cidrs)
    security_group_id    = null
  }

  additional_machine_pools_resolved = var.persists_through_sleep && length(local.network.private_subnet_ids) > 0 ? {
    for pool_name, pool_config in var.additional_machine_pools : pool_name => merge(
      { for k, v in pool_config : k => v if k != "subnet_index" },
      { subnet_id = local.network.private_subnet_ids[pool_config.subnet_index] }
    )
  } : {}
}

module "iam" {
  source = "git::https://github.com/rh-mobb/validated-pattern-terraform-rosa.git//modules/infrastructure/iam?ref=28b293329af938f1f7b5662e7223831eee0df506"

  cluster_name               = var.cluster_name
  account_role_prefix        = var.cluster_name
  operator_role_prefix       = var.cluster_name
  zero_egress                = var.zero_egress
  tags                       = local.tags
  persists_through_sleep     = var.persists_through_sleep
  persists_through_sleep_iam = var.persists_through_sleep_iam

  enable_storage          = true
  etcd_encryption         = var.etcd_encryption
  kms_key_deletion_window = var.kms_key_deletion_window
  enable_efs              = var.enable_efs != null ? var.enable_efs : true

  enable_audit_logging       = var.enable_audit_logging
  enable_cloudwatch_logging  = var.enable_cloudwatch_logging
  enable_cert_manager_iam    = var.enable_cert_manager_iam
  enable_secrets_manager_iam = var.enable_secrets_manager_iam
  aws_private_ca_arn         = var.aws_private_ca_arn
  additional_secrets         = var.additional_secrets

  enable_control_plane_log_forwarding         = var.enable_control_plane_log_forwarding
  control_plane_log_cloudwatch_enabled        = var.control_plane_log_cloudwatch_enabled
  control_plane_log_cloudwatch_log_group_name = var.control_plane_log_cloudwatch_log_group_name
}

module "cluster" {
  source = "git::https://github.com/rh-mobb/validated-pattern-terraform-rosa.git//modules/infrastructure/cluster?ref=28b293329af938f1f7b5662e7223831eee0df506"

  cluster_name = var.cluster_name
  region       = var.region
  vpc_id       = local.network.vpc_id
  vpc_cidr     = var.vpc_cidr

  private_subnet_ids = local.network.private_subnet_ids
  public_subnet_ids  = coalesce(local.network.public_subnet_ids, [])

  installer_role_arn             = module.iam.installer_role_arn
  support_role_arn               = module.iam.support_role_arn
  worker_role_arn                = module.iam.worker_role_arn
  oidc_config_id                 = module.iam.oidc_config_id
  oidc_endpoint_url              = module.iam.oidc_endpoint_url
  enable_persistent_dns_domain   = var.enable_persistent_dns_domain
  persists_through_sleep         = var.persists_through_sleep
  persists_through_sleep_cluster = var.persists_through_sleep_cluster

  http_proxy              = var.http_proxy
  https_proxy             = var.https_proxy
  no_proxy                = var.no_proxy
  additional_trust_bundle = var.additional_trust_bundle

  private            = var.private
  zero_egress        = var.zero_egress
  multi_az           = var.multi_az
  availability_zones = local.network.private_subnet_azs
  fips               = var.fips

  enable_identity_provider     = var.persists_through_sleep
  admin_username               = var.admin_username
  admin_password_for_bootstrap = coalesce(var.admin_password_override, random_password.admin_password.result)

  kms_key_arn      = module.iam.ebs_kms_key_arn
  etcd_kms_key_arn = module.iam.etcd_kms_key_arn
  efs_kms_key_arn  = module.iam.efs_kms_key_arn

  enable_efs           = var.enable_efs != null ? var.enable_efs : true
  private_subnet_cidrs = local.network.private_subnet_cidrs

  enable_audit_logging              = var.enable_audit_logging
  cloudwatch_audit_logging_role_arn = module.iam.cloudwatch_audit_logging_role_arn

  enable_control_plane_log_forwarding         = var.enable_control_plane_log_forwarding
  control_plane_log_forwarding_role_arn       = module.iam.control_plane_log_forwarding_role_arn
  control_plane_log_cloudwatch_groups         = var.control_plane_log_cloudwatch_groups
  control_plane_log_cloudwatch_applications   = var.control_plane_log_cloudwatch_applications
  control_plane_log_s3_groups                 = var.control_plane_log_s3_groups
  control_plane_log_s3_applications           = var.control_plane_log_s3_applications
  control_plane_log_cloudwatch_enabled        = var.control_plane_log_cloudwatch_enabled
  control_plane_log_cloudwatch_log_group_name = var.control_plane_log_cloudwatch_log_group_name
  control_plane_log_s3_enabled                = var.control_plane_log_s3_enabled
  control_plane_log_s3_bucket_name            = var.control_plane_log_s3_bucket_name
  control_plane_log_s3_bucket_prefix          = var.control_plane_log_s3_bucket_prefix
  control_plane_log_s3_retention_days         = var.control_plane_log_s3_retention_days
  resource_suffix                             = random_id.resource_suffix.hex

  enable_gitops_bootstrap = var.enable_gitops_bootstrap != null ? var.enable_gitops_bootstrap : false
  ebs_kms_key_arn         = module.iam.ebs_kms_key_arn
  efs_file_system_id      = null
  git_path                = var.gitops_git_path
  gitops_git_repo_url     = var.gitops_git_repo_url

  enable_termination_protection = var.enable_termination_protection

  aws_private_ca_arn    = var.aws_private_ca_arn
  cert_manager_role_arn = module.iam.cert_manager_role_arn
  openshift_version     = var.openshift_version
  service_cidr          = var.service_cidr
  pod_cidr              = var.pod_cidr
  host_prefix           = var.host_prefix

  default_instance_type = var.default_instance_type
  default_min_replicas  = var.default_min_replicas
  default_max_replicas  = var.default_max_replicas

  additional_machine_pools = {
    for pool_name, pool_config in local.additional_machine_pools_resolved : pool_name => {
      subnet_id                     = pool_config.subnet_id
      instance_type                 = pool_config.instance_type
      autoscaling_enabled           = pool_config.autoscaling_enabled
      min_replicas                  = pool_config.min_replicas
      max_replicas                  = pool_config.max_replicas
      replicas                      = pool_config.replicas
      auto_repair                   = pool_config.auto_repair
      labels                        = pool_config.labels
      taints                        = pool_config.taints
      additional_security_group_ids = pool_config.additional_security_group_ids
      capacity_reservation_id       = pool_config.capacity_reservation_id
      disk_size                     = pool_config.disk_size
      ec2_metadata_http_tokens      = pool_config.ec2_metadata_http_tokens
      tags                          = pool_config.tags
      version                       = pool_config.version
      upgrade_acknowledgements_for  = pool_config.upgrade_acknowledgements_for
      kubelet_configs               = pool_config.kubelet_configs
      tuning_configs                = pool_config.tuning_configs
      ignore_deletion_error         = pool_config.ignore_deletion_error
    }
  }

  wait_for_std_compute_nodes_complete = var.zero_egress ? false : true
  tags                                = var.tags
  additional_cluster_properties       = var.additional_cluster_properties

  depends_on = [module.network_public, module.iam]
}

resource "aws_secretsmanager_secret" "admin_password" {
  name                    = "rosa-hcp-${var.cluster_name}-admin-password"
  description             = "Admin password for ROSA HCP cluster ${var.cluster_name}"
  recovery_window_in_days = 0
  tags = merge(local.tags, {
    Name    = "rosa-hcp-${var.cluster_name}-admin-password"
    Cluster = var.cluster_name
    Purpose = "ClusterAdminPassword"
  })
}

resource "aws_secretsmanager_secret_version" "admin_password" {
  count         = var.persists_through_sleep ? 1 : 0
  secret_id     = aws_secretsmanager_secret.admin_password.id
  secret_string = coalesce(var.admin_password_override, random_password.admin_password.result)

  lifecycle {
    ignore_changes = [secret_string]
  }
}

check "restrict_public_demo_stack" {
  assert {
    condition     = var.network_type == "public" && var.private == false && var.zero_egress == false
    error_message = "This root module expects a public ingress/API cluster: set network_type=public, private=false, zero_egress=false (see terraform.tfvars.example)."
  }
}

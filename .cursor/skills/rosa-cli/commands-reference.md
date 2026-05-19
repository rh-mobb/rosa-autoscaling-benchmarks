# ROSA CLI Command Reference

Auto-generated from `rosa version 1.2.60` on 2026-05-01.
Re-run `scripts/gen-reference.sh` after upgrading the rosa CLI.

This file covers both **ROSA Classic** and **ROSA HCP (Hosted Control Planes)**.
Commands specific to one variant are noted in the relevant help text (look for
`--hosted-cp` / `--classic` flags or variant-specific subcommands).

## rosa (global flags)

```
Command line tool for Red Hat OpenShift Service on AWS.
For further documentation visit https://access.redhat.com/documentation/en-us/red_hat_openshift_service_on_aws

Usage:
  rosa [command]

Available Commands:
  completion  Generates completion scripts
  config      get or set configuration variables
  create      Create a resource from stdin
  delete      Delete a specific resource
  describe    Show details of a specific resource
  download    Download necessary tools for using your cluster
  edit        Edit a specific resource
  grant       Grant role to a specific resource
  help        Help about any command
  init        Applies templates to support Red Hat OpenShift Service on AWS
  install     Installs a resource into a cluster
  link        Link OCM role to specific OCM organization
  list        List all resources of a specific type
  login       Log in to your Red Hat account
  logout      Log out
  logs        Show installation or uninstallation logs for a cluster
  register    Registers a specific resource
  revoke      Revoke role from a specific resource
  token       Generates a token
  uninstall   Uninstalls a resource from a cluster
  unlink      UnLink a ocm/user role from stdin
  upgrade     Upgrade a resource
  verify      Verify resources are configured correctly for cluster install
  version     Prints the version of the tool
  whoami      Displays user account information

Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
  -h, --help           help for rosa

Use "rosa [command] --help" for more information about a command.
```


## rosa config

```
Get or set variables from a configuration file.

The location of the configuration file is gleaned from the 'OCM_CONFIG' environment variable,
or ~/.ocm.json if that variable is unset. Currently using: /Users/pczarkow/Library/Application Support/ocm/ocm.json

The following variables are supported:

	access_token   Bearer access token.
	client_id      OpenID client identifier.
	client_secret  OpenID client secret.
	insecure       Enables insecure communication with the server.
	refresh_token  Offline or refresh token.
	scopes         OpenID scope.
	token_url      OpenID token URL.
	url            URL of the API gateway.
	user_agent     OCM client UserAgent. Default value is used if not set.
	version        OCM client version. Default value is used if not set.
	fedramp        Indicates FedRAMP.

Note that "rosa config get access_token" gives whatever the file contains - may be missing or expired;
you probably want "rosa token" command instead which will obtain a fresh token if needed.

If 'OCM_KEYRING' is set, the configuration file is ignored and the keyring is used instead. The 
following backends are supported for the keyring:

- macOS: keychain, pass
- Linux: secret-service, pass
- Windows: wincred

Available Keyrings on your OS: keychain, keychain, pass

Usage:
  rosa config [command]

Available Commands:
  get         Prints the value of a config variable
  set         Sets the variable's value

Flags:
  -h, --help   help for config

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa config [command] --help" for more information about a command.
```


### rosa config get

```
Prints the value of a config variable. Supported variables are:
access_token
client_id
client_secret
insecure
refresh_token
scopes
token_url
url
user_agent
version
fedramp

Usage:
  rosa config get [flags] VARIABLE

Flags:
  -h, --help   help for get

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa config set

```
Sets the value of a config variable. Supported variables are:
access_token
client_id
client_secret
insecure
refresh_token
token_url
url
user_agent
version
fedramp

Usage:
  rosa config set [flags] VARIABLE VALUE

Flags:
  -h, --help   help for set

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa create

```
Create a resource from stdin

Usage:
  rosa create [command]

Aliases:
  create, add

Available Commands:
  account-roles          Create account-wide IAM roles before creating your cluster.
  admin                  Creates an admin user to login to the cluster
  autoscaler             Create an autoscaler for a cluster
  break-glass-credential Create a break glass credential for a cluster.
  cluster                Create cluster
  decision               Create a decision for an Access Request
  dns-domain             Create DNS Domain.
  external-auth-provider Create an external authentication provider for a cluster.
  iamserviceaccount      Create IAM role for Kubernetes service account
  idp                    Add IDP for cluster
  image-mirror           Create image mirror for a cluster
  kubeletconfig          Create a custom kubeletconfig for a cluster
  log-forwarder          Create a log forwarder for a Hosted Control Plane cluster
  machinepool            Add machine pool to cluster
  network                Network AWS cloudformation stack
  ocm-role               Create role used by OCM
  oidc-config            Create OIDC config compliant with OIDC protocol.
  oidc-provider          Create OIDC provider for an STS cluster.
  operator-roles         Create operator IAM roles for a cluster.
  tuning-configs         Add tuning config
  user-role              Create user role to verify account association

Flags:
  -h, --help             help for create
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa create [command] --help" for more information about a command.
```


### rosa create account-roles

```
Create account-wide IAM roles before creating your cluster.

Usage:
  rosa create account-roles [flags]

Aliases:
  account-roles, accountroles, roles, policies

Examples:
  # Create default account roles for ROSA clusters using STS
  rosa create account-roles

  # Create account roles with a specific permissions boundary
  rosa create account-roles --permissions-boundary arn:aws:iam::123456789012:policy/perm-boundary

Flags:
      --classic                        Create only classic Rosa account roles
  -f, --force-policy-creation          Forces creation of policies skipping compatibility check
  -h, --help                           help for account-roles
      --hosted-cp                      Enable the use of Hosted Control Planes
  -i, --interactive                    Enable interactive mode.
  -m, --mode string                    How to perform the operation. Valid options are:
                                       auto: Resource changes will be automatic applied using the current AWS account
                                       manual: Commands necessary to modify AWS resources will be output to be run manually
      --path string                    The arn path for the account/operator roles as well as their policies
      --permissions-boundary string    The ARN of the policy that is used to set the permissions boundary for the account roles.
      --prefix string                  User-defined prefix for all generated AWS resources (default "ManagedOpenShift")
      --route53-role-arn string        Role ARN associated with the private hosted zone used for Hosted Control Plane cluster shared VPC, this role contains policies to be used with Route 53
      --version string                 Version of OpenShift that will be used to setup policy tag, for example "4.11"
      --vpc-endpoint-role-arn string   Role ARN associated with the shared VPC used for Hosted Control Plane clusters, this role contains policies to be used with the VPC endpoint
  -y, --yes                            Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa create admin

```
Creates a cluster-admin user with an auto-generated password to login to the cluster

Usage:
  rosa create admin [flags]

Examples:
  # Create an admin user to login to the cluster
  rosa create admin -c mycluster -p MasterKey123

Flags:
  -c, --cluster string    Name or ID of the cluster.
  -h, --help              help for admin
  -o, --output string     Output format. Allowed formats are [json yaml]
  -p, --password string   Choice of password for admin user.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create autoscaler

```
     Configuring cluster-wide autoscaling behavior. At least one machine-pool should have autoscaling enabled for the configuration to be active. Supported only on ROSA clusters with self-hosted Control Plane (Classic)

Usage:
  rosa create autoscaler [flags]

Aliases:
  autoscaler, cluster-autoscaler

Examples:
  # Interactively create an autoscaler to a cluster named "mycluster"
  rosa create autoscaler --cluster=mycluster --interactive

  # Create a cluster-autoscaler where it should skip nodes with local storage
  rosa create autoscaler --cluster=mycluster --skip-nodes-with-local-storage

  # Create a cluster-autoscaler with log verbosity of '3'
  rosa create autoscaler --cluster=mycluster --log-verbosity 3

  # Create a cluster-autoscaler with total CPU constraints
  rosa create autoscaler --cluster=mycluster --min-cores 10 --max-cores 100

Flags:
  -c, --cluster string                           Name or ID of the cluster.
  -i, --interactive                              Enable interactive mode.
      --balance-similar-node-groups              Identify node groups with the same instance type and label set, and aim to balance respective sizes of those node groups. Only supported for self-hosted (Classic) control plane clusters.
      --skip-nodes-with-local-storage            If true cluster autoscaler will never delete nodes with pods with local storage, e.g. EmptyDir or HostPath. Only supported for self-hosted (Classic) control plane clusters.
      --log-verbosity int                        Autoscaler log level. Default is 1, 4 is a good option when trying to debug the autoscaler. Only supported for self-hosted (Classic) control plane clusters. (default 1)
      --max-pod-grace-period int                 Gives pods graceful termination time before scaling down, measured in seconds. (default 600)
      --pod-priority-threshold int               The priority that a pod must exceed to cause the cluster autoscaler to deploy additional nodes. Expects an integer, can be negative. (default -10)
      --ignore-daemonsets-utilization            Should cluster-autoscaler ignore DaemonSet pods when calculating resource utilization for scaling down. Only supported for self-hosted (Classic) control plane clusters.
      --max-node-provision-time string           Maximum time cluster-autoscaler waits for node to be provisioned. Expects string comprised of an integer and time unit (ns|us|µs|ms|s|m|h), examples: 20m, 1h. (default "15m")
      --balancing-ignored-labels strings         A comma-separated list of label keys that cluster autoscaler should ignore when considering node group similarity. Only supported for self-hosted (Classic) control plane clusters.
      --max-nodes-total int                      Total amount of nodes that can exist in the cluster, including non-scaled nodes.
      --min-cores int                            Minimum limit for the amount of cores to deploy in the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --max-cores int                            Maximum limit for the amount of cores to deploy in the cluster. Only supported for self-hosted (Classic) control plane clusters. (default 11520)
      --min-memory int                           Minimum limit for the amount of memory, in GiB, in the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --max-memory int                           Maximum limit for the amount of memory, in GiB, in the cluster. Only supported for self-hosted (Classic) control plane clusters. (default 230400)
      --gpu-limit stringArray                    Limit GPUs consumption. It should be comprised of 3 values separated with commas: the GPU hardware type, a minimal count for that type and a maximal count for that type. This option can be repeated multiple times in order to apply multiple restrictions for different GPU types. Only supported for self-hosted (Classic) control plane clusters. For example: --gpu-limit nvidia.com/gpu,0,10 --gpu-limit amd.com/gpu,1,5
      --scale-down-enabled                       Should cluster-autoscaler be able to scale down the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-unneeded-time string          Increasing value will make nodes stay up longer, waiting for pods to be scheduled while decreasing value will make nodes be deleted sooner. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-utilization-threshold float   Node utilization level, defined as sum of requested resources divided by capacity, below which a node can be considered for scale down. Value should be between 0 and 1. Only supported for self-hosted (Classic) control plane clusters. (default 0.5)
      --scale-down-delay-after-add string        After a scale-up, consider scaling down only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-delay-after-delete string     After a scale-down, consider scaling down again only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-delay-after-failure string    After a failing scale-down, consider scaling down again only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
  -h, --help                                     help for autoscaler

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create break-glass-credential

```
Create a break glass credential for a hosted control plane cluster with external authentication enabled.

Usage:
  rosa create break-glass-credential [flags]

Aliases:
  break-glass-credential, break-glass-credentials, breakglasscredential, breakglasscredentials

Examples:
  # Interactively create a break glass credential to a cluster named "mycluster"
  rosa create break-glass-credential --cluster=mycluster --interactive

Flags:
  -c, --cluster string        Name or ID of the cluster.
      --expiration duration   Expire the break glass credential after a relative duration like 2h, 8h. The expiration duration needs to be at least 10 minutes from now and to be at maximum 24 hours.
  -h, --help                  help for break-glass-credential
  -i, --interactive           Enable interactive mode.
      --username string       Username for the break glass credential.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create cluster

```
Create cluster.

Usage:
  rosa create cluster [flags]

Examples:
  # Create a cluster named "mycluster"
  rosa create cluster --cluster-name=mycluster

  # Create a cluster in the us-east-2 region
  rosa create cluster --cluster-name=mycluster --region=us-east-2

Flags:
  -c, --cluster-name string                                    The unique name of the cluster. The name can be used as the identifier of the cluster. The maximum length is 54 characters.Once set, the cluster name cannot be changed
      --domain-prefix string                                   An optional unique domain prefix of the cluster. This will be used when generating a sub-domain for your cluster on openshiftapps.com. It must be unique per organization and consist of lowercase alphanumeric characters or '-', start with an alphabetic character, and end with an alphanumeric character. The maximum length is 15 characters. Once set, the cluster domain prefix cannot be changed
      --sts                                                    Use AWS Security Token Service (STS) instead of IAM credentials to deploy your cluster.
      --non-sts                                                Use legacy method of creating clusters (IAM mode).
      --mint-mode                                              Use legacy method of creating clusters (IAM mode). This is an alias for --non-sts.
      --role-arn string                                        The Amazon Resource Name of the role that OpenShift Cluster Manager will assume to create the cluster.
      --external-id string                                     An optional unique identifier that might be required when you assume a role in another account.
      --support-role-arn string                                The Amazon Resource Name of the role used by Red Hat SREs to enable access to the cluster account in order to provide support.
      --controlplane-iam-role-arn string                       The IAM role ARN that will be attached to control plane instances.
      --worker-iam-role-arn string                             The IAM role ARN that will be attached to worker instances.
      --operator-roles-prefix string                           Prefix to use for all IAM roles used by the operators needed in the OpenShift installer. Leave empty to use an auto-generated one.
      --oidc-config-id string                                  Registered OIDC Configuration ID to use for cluster creation
      --external-auth-providers-enabled                        Enable external authentication configuration for a Hosted Control Plane cluster.
      --tags strings                                           Apply user defined tags to all resources created by ROSA in AWS. Tags are comma separated, for example: 'key value, foo bar'
      --multi-az                                               Deploy to multiple data centers.
      --region string                                          Use a specific AWS region, overriding the AWS_REGION environment variable.
      --version string                                         Version of OpenShift that will be used to install the cluster, for example "4.3.10"
      --channel-group string                                   Channel group is the name of the group where this image belongs, for example "stable" or "fast". (default "stable")
      --etcd-encryption                                        Add etcd encryption. By default etcd data is encrypted at rest. This option configures etcd encryption on top of existing storage encryption.
      --fips                                                   Create cluster that uses FIPS Validated / Modules in Process cryptographic libraries.
      --http-proxy string                                      A proxy URL to use for creating HTTP connections outside the cluster. The URL scheme must be http.
      --https-proxy string                                     A proxy URL to use for creating HTTPS connections outside the cluster.
      --no-proxy strings                                       A comma-separated list of destination domain names, domains, IP addresses or other network CIDRs to exclude proxying.
      --additional-trust-bundle-file string                    A file contains a PEM-encoded X.509 certificate bundle that will be added to the nodes' trusted certificate store.
      --additional-allowed-principals strings                  A comma-separated list of additional allowed principal ARNs to be added to the Hosted Control Plane's VPC Endpoint Service to enable additional VPC Endpoint connection requests to be automatically accepted.
      --enable-customer-managed-key                            Enable to specify your KMS Key to encrypt EBS instance volumes. By default account’s default KMS key for that particular region is used.
      --kms-key-arn string                                     The key ARN is the Amazon Resource Name (ARN) of a CMK. It is a unique, fully qualified identifier for the CMK. A key ARN includes the AWS account, Region, and the key ID.
      --etcd-encryption-kms-arn string                         The etcd encryption kms key ARN is the key used to encrypt etcd. If set it will override etcd-encryption flag to true. It is a unique, fully qualified identifier for the CMK. A key ARN includes the AWS account, Region, and the key ID.
      --private-link                                           Provides private connectivity between VPCs, AWS services, and your on-premises networks, without exposing your traffic to the public internet.
                                                               
                                                               --private-link is only to be used with Classic clusters after ROSA CLI v1.2.55. 
                                                               For Hosted Control Plane clusters, use the '--private' and '--default-ingress-private' flags instead.
      --default-ingress-private                                Listening method for default cluster ingress. Internal = private, External = non-private.
      --ec2-metadata-http-tokens string                        Should cluster nodes use both v1 and v2 endpoints or just v2 endpoint of EC2 Instance Metadata Service (IMDS)
      --subnet-ids strings                                     The Subnet IDs to use when installing the cluster. Format should be a comma-separated list. Leave empty for installer provisioned subnet IDs.
      --availability-zones strings                             The availability zones to use when installing a non-BYOVPC cluster. Format should be a comma-separated list. Leave empty for the installer to pick availability zones
      --compute-machine-type string                            Instance type for the compute nodes. Determines the amount of memory and vCPU allocated to each compute node.
      --replicas int                                           Number of worker nodes to provision. Single zone clusters need at least 2 nodes, multizone clusters need at least 3 nodes. Hosted clusters require that the number of worker nodes be a multiple of the number of private subnets. (default 2)
      --enable-autoscaling                                     Enable autoscaling of compute nodes.
      --registry-config-allowed-registries strings             A comma-separated list of registries for which image pull and push actions are allowed.
      --registry-config-insecure-registries strings            A comma-separated list of registries which do not have a valid TLS certificate or only support HTTP connections.
      --registry-config-blocked-registries strings             A comma-separated list of registries for which image pull and push actions are denied.
      --registry-config-allowed-registries-for-import string   Limits the container image registries from which normal users can import images. The format should be a comma-separated list of 'domainName:insecure'. 'domainName' specifies a domain name for the registry. 'insecure' indicates whether the registry is secure or insecure.
      --registry-config-additional-trusted-ca string           A json file containing the registry hostname as the key, and the PEM-encoded certificate as the value, for each additional registry CA to trust.
      --autoscaler-balance-similar-node-groups                 Identify node groups with the same instance type and label set, and aim to balance respective sizes of those node groups. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-skip-nodes-with-local-storage               If true cluster autoscaler will never delete nodes with pods with local storage, e.g. EmptyDir or HostPath. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-log-verbosity int                           Autoscaler log level. Default is 1, 4 is a good option when trying to debug the autoscaler. Only supported for self-hosted (Classic) control plane clusters. (default 1)
      --autoscaler-max-pod-grace-period int                    Gives pods graceful termination time before scaling down, measured in seconds. (default 600)
      --autoscaler-pod-priority-threshold int                  The priority that a pod must exceed to cause the cluster autoscaler to deploy additional nodes. Expects an integer, can be negative. (default -10)
      --autoscaler-ignore-daemonsets-utilization               Should cluster-autoscaler ignore DaemonSet pods when calculating resource utilization for scaling down. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-max-node-provision-time string              Maximum time cluster-autoscaler waits for node to be provisioned. Expects string comprised of an integer and time unit (ns|us|µs|ms|s|m|h), examples: 20m, 1h. (default "15m")
      --autoscaler-balancing-ignored-labels strings            A comma-separated list of label keys that cluster autoscaler should ignore when considering node group similarity. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-max-nodes-total int                         Total amount of nodes that can exist in the cluster, including non-scaled nodes.
      --autoscaler-min-cores int                               Minimum limit for the amount of cores to deploy in the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-max-cores int                               Maximum limit for the amount of cores to deploy in the cluster. Only supported for self-hosted (Classic) control plane clusters. (default 11520)
      --autoscaler-min-memory int                              Minimum limit for the amount of memory, in GiB, in the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-max-memory int                              Maximum limit for the amount of memory, in GiB, in the cluster. Only supported for self-hosted (Classic) control plane clusters. (default 230400)
      --autoscaler-gpu-limit stringArray                       Limit GPUs consumption. It should be comprised of 3 values separated with commas: the GPU hardware type, a minimal count for that type and a maximal count for that type. This option can be repeated multiple times in order to apply multiple restrictions for different GPU types. Only supported for self-hosted (Classic) control plane clusters. For example: --autoscaler-gpu-limit nvidia.com/gpu,0,10 --autoscaler-gpu-limit amd.com/gpu,1,5
      --autoscaler-scale-down-enabled                          Should cluster-autoscaler be able to scale down the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-scale-down-unneeded-time string             Increasing value will make nodes stay up longer, waiting for pods to be scheduled while decreasing value will make nodes be deleted sooner. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-scale-down-utilization-threshold float      Node utilization level, defined as sum of requested resources divided by capacity, below which a node can be considered for scale down. Value should be between 0 and 1. Only supported for self-hosted (Classic) control plane clusters. (default 0.5)
      --autoscaler-scale-down-delay-after-add string           After a scale-up, consider scaling down only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-scale-down-delay-after-delete string        After a scale-down, consider scaling down again only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
      --autoscaler-scale-down-delay-after-failure string       After a failing scale-down, consider scaling down again only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
      --min-replicas int                                       Minimum number of compute nodes. (default 2)
      --max-replicas int                                       Maximum number of compute nodes. (default 2)
      --worker-mp-labels string                                Labels for the worker machine pool. Format should be a comma-separated list of 'key=value'. This list will overwrite any modifications made to Node labels on an ongoing basis.
      --machine-cidr ipNet                                     Block of IP addresses used by OpenShift while installing the cluster, for example "10.0.0.0/16".
      --service-cidr ipNet                                     Block of IP addresses for services, for example "172.30.0.0/16".
      --pod-cidr ipNet                                         Block of IP addresses from which Pod IP addresses are allocated, for example "10.128.0.0/14".
      --host-prefix int                                        Subnet prefix length to assign to each individual node. For example, if host prefix is set to "23", then each node is assigned a /23 subnet out of the given CIDR.
      --private                                                Restrict master API endpoint and application routes to direct, private connectivity.
      --disable-scp-checks                                     Indicates if cloud permission checks are disabled when attempting installation of the cluster.
      --disable-workload-monitoring                            Enables you to monitor your own projects in isolation from Red Hat Site Reliability Engineer (SRE) platform metrics. Not supported for Hosted Control Plane clusters.
  -w, --watch                                                  Watch cluster installation logs.
      --dry-run                                                Simulate creating the cluster.
      --permissions-boundary string                            The ARN of the policy that is used to set the permissions boundary for the operator roles in STS clusters.
      --hosted-cp                                              Enable the use of Hosted Control Planes
      --worker-disk-size string                                Default worker machine pool root disk size with a **unit suffix** like GiB or TiB, e.g. 200GiB.
      --billing-account string                                 Account ID used for billing subscriptions purchased through the AWS console for ROSA
      --create-admin-user                                      Create cluster admin named "cluster-admin"
      --no-cni                                                 Disable CNI creation to let users bring their own CNI.
      --cluster-admin-password string                          The password must
                                                               		- Be at least 14 characters (ASCII-standard) without whitespaces
                                                               		- Include uppercase letters, lowercase letters, and numbers or symbols (ASCII-standard characters only)
      --audit-log-arn string                                   The ARN of the role that is used to forward audit logs to AWS CloudWatch.
      --default-ingress-route-selector string                  Route Selector for ingress. Format should be a comma-separated list of 'key=value'. If no label is specified, all routes will be exposed on both routers. For legacy ingress support these are inclusion labels, otherwise they are treated as exclusion label.
      --default-ingress-excluded-namespaces string             Excluded namespaces for ingress. Format should be a comma-separated list 'value1, value2...'. If no values are specified, all namespaces will be exposed.
      --default-ingress-wildcard-policy string                 Wildcard Policy for ingress. Options are WildcardsDisallowed,WildcardsAllowed. Default is 'WildcardsDisallowed'.
      --default-ingress-namespace-ownership-policy string      Namespace Ownership Policy for ingress. Options are Strict,InterNamespaceAllowed. Default is 'Strict'.
      --vpc-endpoint-role-arn string                           AWS IAM Role ARN with policy attached, associated with the shared VPC. Grants permissions necessary to communicate with and handle a Hosted Control Plane cross-account VPC.
      --route53-role-arn string                                AWS IAM Role Arn with policy attached, associated with shared VPC. Grants permission necessary to handle route53 operations associated with a cross-account VPC. This flag deprecates '--shared-vpc-role-arn'.
      --hcp-internal-communication-hosted-zone-id string       The internal communication Route 53 hosted zone ID to be used for Hosted Control Plane cross-account VPC, e.g., 'Z05646003S02O1ENCDCSN'.
      --ingress-private-hosted-zone-id string                  ID assigned by AWS to private Route 53 hosted zone associated with intended shared VPC, e.g., 'Z05646003S02O1ENCDCSN'.
      --base-domain string                                     Base DNS domain name previously reserved and matching the hosted zone name of the private Route 53 hosted zone associated with intended shared VPC, e.g., '1vo8.p1.openshiftapps.com'.
      --additional-compute-security-group-ids strings          The additional Security Group IDs to be added to the default worker machine pool. Format should be a comma-separated list.
      --additional-infra-security-group-ids strings            The additional Security Group IDs to be added to the infra worker nodes. Format should be a comma-separated list.
      --additional-control-plane-security-group-ids strings    The additional Security Group IDs to be added to the control plane nodes. Format should be a comma-separated list.
      --log-fwd-config string                                  A path to a log forwarding config file. This should be a YAML file with the following structure:
                                                               
                                                               cloudwatch:
                                                                 cloudwatch_log_role_arn: "role_arn_here"
                                                                 cloudwatch_log_group_name: "group_name_here"
                                                                 applications: ["example_app_1", "example_app_2"]
                                                                 groups: ["group-name", "group_name-2"]
                                                               s3:
                                                                 s3_config_bucket_name: "bucket_name_here"
                                                                 s3_config_bucket_prefix: "bucket_prefix_here"
                                                                 applications: ["example_app_1", "example_app_2"]
                                                                 groups: ["group-name"]
  -m, --mode string                                            How to perform the operation. Valid options are:
                                                               auto: Resource changes will be automatic applied using the current AWS account
                                                               manual: Commands necessary to modify AWS resources will be output to be run manually
  -i, --interactive                                            Enable interactive mode.
  -o, --output string                                          Output format. Allowed formats are [json yaml]
  -y, --yes                                                    Automatically answer yes to confirm operation.
  -h, --help                                                   help for cluster

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
```


### rosa create decision

```
Create a decision for an Access Request

Usage:
  rosa create decision [flags]

Examples:
  # Create a decision for an Access Request to approve it
  rosa create decision --access-request <access_request_id> --decision Approved
  

Flags:
  -a, --access-request string   ID of the Access Request to add decision (required).
  -d, --decision string         Decision created for the Access Request, valid values are 'Approved' or 'Denied' (required).
  -h, --help                    help for decision
  -j, --justification string    Justification for the decision, required if decision is 'Denied'.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create dns-domain

```
Create DNS Domain.

Usage:
  rosa create dns-domain [flags]

Aliases:
  dns-domain, dnsdomain

Examples:
  # Create DNS Domain
	rosa create dns-domain

Flags:
  -h, --help        help for dns-domain
      --hosted-cp   If creating a dns-domain for a Hosted Control Plane cluster

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create external-auth-provider

```
Configure a cluster to use an external authentication provider instead of an internal oidc provider.

Usage:
  rosa create external-auth-provider [flags]

Aliases:
  external-auth-provider, externalauthproviders, externalauthprovider, external-auth-providers

Examples:
  # Interactively create an external authentication provider to a cluster named "mycluster"
  rosa create external-auth-provider --cluster=mycluster --interactive

Flags:
      --claim-mapping-groups-claim string     Describes rules on how to transform information from an ID token into a cluster identity.
      --claim-mapping-username-claim string   The name of the claim that should be used to construct usernames for the cluster identity.
      --claim-validation-rule strings         ClaimValidationRules are rules that are applied to validate token claims to authenticate users. The input will be in a <claim>:<required_value> format. To have multiple claim validation rules, you could separate the values by ','. The input could be in a <claim>:<required_value>,<claim>:<required_value> format. 
  -c, --cluster string                        Name or ID of the cluster.
      --console-client-id string              The application or client id for your app registration that is used for console.
      --console-client-secret string          The value of the client secret that is associated with your console app registration.
  -h, --help                                  help for external-auth-provider
  -i, --interactive                           Enable interactive mode.
      --issuer-audiences strings              A comma-separated list of audiences that the token was issued for.
      --issuer-ca-file string                 Path to certificate file to use when making requests to the issuer server.
      --issuer-url string                     The serving url of the token issuer.
      --name string                           Name for the external authentication provider.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create iamserviceaccount

```
Create an IAM role that can be assumed by a Kubernetes service account using OpenID Connect (OIDC) identity federation. This allows pods running in the service account to assume the IAM role and access AWS resources.

Usage:
  rosa create iamserviceaccount [flags]

Aliases:
  iamserviceaccount, iam-service-account

Examples:
  # Create an IAM role for a service account
  rosa create iamserviceaccount --cluster my-cluster --name my-app --namespace default

Flags:
      --attach-policy-arn strings     ARN of the IAM policy to attach to the role (can be used multiple times).
  -c, --cluster string                Name or ID of the cluster.
  -h, --help                          help for iamserviceaccount
      --inline-policy string          Inline policy document (JSON) or path to policy file (use file://path/to/policy.json).
  -i, --interactive                   Enable interactive mode.
  -m, --mode string                   How to perform the operation. Valid options are:
                                      auto: Resource changes will be automatic applied using the current AWS account
                                      manual: Commands necessary to modify AWS resources will be output to be run manually
      --name strings                  Name of the Kubernetes service account (can be used multiple times).
      --namespace string              Kubernetes namespace for the service account. (default "default")
      --path string                   IAM path for the role.
      --permissions-boundary string   ARN of the IAM policy to use as permissions boundary.
      --role-name string              Name of the IAM role (auto-generated if not specified).

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create idp

```
Add an Identity providers to determine how users log into the cluster.

Usage:
  rosa create idp [flags]

Examples:
  # Add a GitHub identity provider to a cluster named "mycluster"
  rosa create idp --type=github --cluster=mycluster

  # Add an identity provider following interactive prompts
  rosa create idp --cluster=mycluster --interactive

Flags:
  -c, --cluster string               Name or ID of the cluster.
  -t, --type string                  Type of identity provider. Options are [github gitlab google htpasswd ldap openid].
      --name string                  Name for the identity provider.
                                     
      --mapping-method string        Specifies how new identities are mapped to users when they log in. Options are [add claim generate lookup] (default "claim")
      --client-id string             Client ID from the registered application.
      --client-secret string         Client Secret from the registered application.
      --ca string                    Path to PEM-encoded certificate file to use when making requests to the server.
                                     
      --hostname string              GitHub: Optional domain to use with a hosted instance of GitHub Enterprise.
      --organizations string         GitHub: Only users that are members of at least one of the listed organizations will be allowed to log in.
      --teams string                 GitHub: Only users that are members of at least one of the listed teams will be allowed to log in. The format is <org>/<team>.
                                     
      --host-url string              GitLab: The host URL of a GitLab provider. (default "https://gitlab.com")
      --hosted-domain string         Google: Restrict users to a Google Apps domain.
                                     
      --url string                   LDAP: An RFC 2255 URL which specifies the LDAP search parameters to use.
      --insecure                     LDAP: Do not make TLS connections to the server.
      --bind-dn string               LDAP: DN to bind with during the search phase.
      --bind-password string         LDAP: Password to bind with during the search phase.
      --id-attributes string         LDAP: The list of attributes whose values should be used as the user ID. (default "dn")
      --username-attributes string   LDAP: The list of attributes whose values should be used as the preferred username. (default "uid")
      --name-attributes string       LDAP: The list of attributes whose values should be used as the display name. (default "cn")
      --email-attributes string      LDAP: The list of attributes whose values should be used as the email address.
                                     
      --issuer-url string            OpenID: The URL that the OpenID Provider asserts as the Issuer Identifier. It must use the https scheme with no URL query parameters or fragment.
      --email-claims string          OpenID: List of claims to use as the email address.
      --name-claims string           OpenID: List of claims to use as the display name.
      --username-claims string       OpenID: List of claims to use as the preferred username when provisioning a user.
      --groups-claims string         OpenID: List of claims to use as the groups names.
      --extra-scopes string          OpenID: List of scopes to request, in addition to the 'openid' scope, during the authorization token request.
                                     
  -u, --users strings                HTPasswd: List of users to add to the IDP. 
                                     It must be a comma separated list of  username:password, i.e user1:password,user2:password 
                                     
      --from-file string             HTPasswd: Path to a well formed htpasswd file.
                                     
  -i, --interactive                  Enable interactive mode.
  -h, --help                         help for idp

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create image-mirror

```
Create an image mirror configuration for a Hosted Control Plane cluster. The image mirror ID will be auto-generated.

Usage:
  rosa create image-mirror [flags]

Aliases:
  image-mirror, image-mirrors

Examples:
  # Create an image mirror for cluster "mycluster"
  rosa create image-mirror --cluster=mycluster \
    --source=registry.example.com/team \
    --mirrors=mirror.corp.com/team,backup.corp.com/team

  # Create with a specific type (digest is default and only supported type)
  rosa create image-mirror --cluster=mycluster \
    --type=digest --source=docker.io/library \
    --mirrors=internal-registry.company.com/dockerhub

Flags:
  -c, --cluster string    Name or ID of the cluster.
  -h, --help              help for image-mirror
      --mirrors strings   List of mirror registries (comma-separated, required)
      --profile string    Use a specific AWS profile from your credential file.
      --region string     Use a specific AWS region, overriding the AWS_REGION environment variable.
      --source string     Source registry that will be mirrored (required)
      --type string       Type of image mirror (default: digest) (default "digest")

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
  -y, --yes            Automatically answer yes to confirm operation.
```


### rosa create kubeletconfig

```
Create a custom kubeletconfig for a cluster

Usage:
  rosa create kubeletconfig [flags]

Aliases:
  kubeletconfig, kubelet-config

Examples:
  # Create a custom kubeletconfig with a pod-pids-limit of 5000
  rosa create kubeletconfig --cluster=mycluster --pod-pids-limit=5000
  

Flags:
      --pod-pids-limit int   Sets the requested pod_pids_limit for this KubeletConfig.
      --name string          Name of the KubeletConfig (required for Hosted Control Plane clusters)
  -c, --cluster string       Name or ID of the cluster.
  -i, --interactive          Enable interactive mode.
  -h, --help                 help for kubeletconfig

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create log-forwarder

```
Create a log forwarder to forward logs from a hosted cluster to external services such as S3 or CloudWatch. Must create for an existing Hosted Control Plane cluster

Usage:
  rosa create log-forwarder -c <cluster-id> [flags]

Aliases:
  log-forwarder, logforwarder, log-forwarder

Examples:
  # Create a log forwarder using a config file
  rosa create log-forwarder -c mycluster-hcp --log-fwd-config=s3.yml
  
  # Create a log forwarder interactively
  rosa create log-forwarder -c mycluster-hcp --interactive

Flags:
  -c, --cluster string          Name or ID of the cluster.
  -h, --help                    help for log-forwarder
  -i, --interactive             Enable interactive mode.
      --log-fwd-config string   A path to a log forwarding config file. This should be a YAML file with the following structure:
                                
                                cloudwatch:
                                  cloudwatch_log_role_arn: "role_arn_here"
                                  cloudwatch_log_group_name: "group_name_here"
                                  applications: ["example_app_1", "example_app_2"]
                                  groups: ["group-name", "group_name-2"]
                                s3:
                                  s3_config_bucket_name: "bucket_name_here"
                                  s3_config_bucket_prefix: "bucket_prefix_here"
                                  applications: ["example_app_1", "example_app_2"]
                                  groups: ["group-name"]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create machinepool

```
Add a machine pool to the cluster.

Usage:
  rosa create machinepool [flags]

Aliases:
  machinepool, machinepools, machine-pool, machine-pools

Examples:
  # Interactively add a machine pool to a cluster named "mycluster"
  rosa create machinepool --cluster=mycluster --interactive
  # Add a machine pool mp-1 with 3 replicas of m5.xlarge to a cluster
  rosa create machinepool --cluster=mycluster --name=mp-1 --replicas=3 --instance-type=m5.xlarge
  # Add a machine pool mp-1 with autoscaling enabled and 3 to 6 replicas of m5.xlarge to a cluster
  rosa create machinepool --cluster=mycluster --name=mp-1 --enable-autoscaling \
	--min-replicas=3 --max-replicas=6 --instance-type=m5.xlarge
  # Add a machine pool with labels to a cluster
  rosa create machinepool -c mycluster --name=mp-1 --replicas=2 --instance-type=r5.2xlarge --labels=foo=bar,bar=baz,
  # Add a machine pool with spot instances to a cluster
  rosa create machinepool -c mycluster --name=mp-1 --replicas=2 --instance-type=r5.2xlarge --use-spot-instances \
    --spot-max-price=0.5
  # Add a machine pool to a cluster and set the node drain grace period
  rosa create machinepool -c mycluster --name=mp-1 --node-drain-grace-period="90 minutes"

Flags:
      --additional-security-group-ids strings    The additional Security Group IDs to be added to the machine pool. Format should be a comma-separated list.
      --autorepair                               Select auto-repair behaviour for a machinepool in a hosted cluster. (default true)
      --availability-zone string                 Select availability zone to create a single AZ machine pool for a multi-AZ cluster
      --capacity-reservation-id string           The ID of an AWS On-Demand Capacity Reservation. The 'capacity-reservation-id' must be pre-created in advance, before creating a NodePool.
      --capacity-reservation-preference string   A configurable preference for a capacity-reservation. Options are: 'none' | 'capacity-reservations-only' | 'open'
  -c, --cluster string                           Name or ID of the cluster.
      --disk-size string                         Root disk size with a suffix like GiB or TiB
      --ec2-metadata-http-tokens string          Should cluster nodes use both v1 and v2 endpoints or just v2 endpoint of EC2 Instance Metadata Service (IMDS)This flag is only supported for Hosted Control Planes.
      --enable-autoscaling                       Enable autoscaling for the machine pool.
  -h, --help                                     help for machinepool
      --instance-type string                     Instance type that should be used. (default "m5.xlarge")
  -i, --interactive                              Enable interactive mode.
      --kubelet-configs string                   Name of the kubelet config to be applied to the machine pool. A single kubelet config is allowed. Kubelet config must already exist. This will overwrite any modifications made to node kubelet configs on an ongoing basis.
      --labels string                            Labels for machine pool. Format should be a comma-separated list of 'key=value'. This list will overwrite any modifications made to Node labels on an ongoing basis.
      --max-replicas int                         Maximum number of machines for the machine pool.
      --max-surge string                         The maximum number of nodes that can be provisioned above the desired number of nodes in the machinepool during the upgrade. It can be an absolute number i.e. 1, or a percentage i.e. '20%'. (default "1")
      --max-unavailable string                   The maximum number of nodes in the machinepool that can be unavailable during the upgrade. It can be an absolute number i.e. 1, or a percentage i.e. '20%'. (default "0")
      --min-replicas int                         Minimum number of machines for the machine pool.
      --multi-availability-zone                  Create a multi-AZ machine pool for a multi-AZ cluster (default true)
      --name string                              Name for the machine pool (required).
      --node-drain-grace-period string           You may set a grace period for how long Pod Disruption Budget-protected workloads will be respected when the NodePool is being replaced or upgraded.
                                                 After this grace period, all remaining workloads will be forcibly evicted.
                                                 Valid value is from 0 to 1 week (10080 minutes), and the supported units are 'minute|minutes' or 'hour|hours'. 0 or empty value means that the NodePool can be drained without any time limitations.
                                                 This flag is only supported for Hosted Control Planes.
  -o, --output string                            Output format. Allowed formats are [json yaml]
      --replicas int                             Count of machines for the machine pool (required when autoscaling is disabled).
      --spot-max-price string                    Max price for spot instance. If empty use the on-demand price. (default "on-demand")
      --subnet string                            Select subnet to create a single AZ machine pool for BYOVPC cluster
      --tags strings                             Apply user defined tags to all resources created by ROSA in AWS. Tags are comma separated, for example: 'key value, foo bar'
      --taints string                            Taints for machine pool. Format should be a comma-separated list of 'key=value:ScheduleType'. This list will overwrite any modifications made to Node taints on an ongoing basis.
      --tuning-configs string                    Name of the tuning configs to be applied to the machine pool. Format should be a comma-separated list. Tuning config must already exist. This list will overwrite any modifications made to node tuning configs on an ongoing basis.
      --type string                              Specifies the type of AMI this machinepool uses. You may supply '--type Windows' for example if you want support for Windows VMs.
      --use-spot-instances                       Use spot instances for the machine pool.
      --version string                           Version of OpenShift that will be used to install a machine pool for a hosted cluster, for example "4.12.4"

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create network

```
Available parameters in default template:
  AZ1
  AZ2
  AZ3
  AZ4
  AvailabilityZoneCount
  Name
  Region
  VpcCidr
  Tags

Usage:
  rosa create network [flags]

Aliases:
  network, networks

Examples:
  # Create a AWS cloudformation stack
  rosa create network <template-name> --param Param1=Value1 --param Param2=Value2 

  # ROSA quick start HCP VPC example with one availability zone
  rosa create network rosa-quickstart-default-vpc --param Region=us-west-2 --param Name=quickstart-stack --param AvailabilityZoneCount=1 --param VpcCidr=10.0.0.0/16

  # ROSA quick start HCP VPC example with two explicit availability zones
  rosa create network rosa-quickstart-default-vpc --param Region=us-west-2 --param Name=quickstart-stack --param AZ1=us-west-2b --param AZ2=us-west-2d --param VpcCidr=10.0.0.0/16

  # To delete the AWS cloudformation stack
  aws cloudformation delete-stack --stack-name <name> --region <region>

# TEMPLATE_NAME:
Specifies the name of the template to use. This should match the name of a directory 
under the path specified by '--template-dir' or the 'OCM_TEMPLATE_DIR' environment variable.
The directory should contain a YAML file defining the custom template structure.

If no TEMPLATE_NAME is provided, or if no matching directory is found, the default 
built-in template 'rosa-quickstart-default-vpc' will be used.

Flags:
  -h, --help                  help for network
  -m, --mode string           How to perform the operation. Valid options are:
                              auto: Resource changes will be automatic applied using the current AWS account
                              manual: Commands necessary to modify AWS resources will be output to be run manually
      --param stringArray     List of parameters
      --template-dir string   Use a specific template directory, overriding the OCM_TEMPLATE_DIR environment variable.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create ocm-role

```
Create role used by OCM to verify necessary roles and OIDC providers are in place.

Usage:
  rosa create ocm-role [flags]

Aliases:
  ocm-role, ocmrole

Examples:
  # Create default ocm role for ROSA clusters using STS
  rosa create ocm-role

  # Create ocm role with a specific permissions boundary
  rosa create ocm-role --permissions-boundary arn:aws:iam::123456789012:policy/perm-boundary

Flags:
      --admin                         Enable admin capabilities for the role
  -h, --help                          help for ocm-role
  -i, --interactive                   Enable interactive mode.
  -m, --mode string                   How to perform the operation. Valid options are:
                                      auto: Resource changes will be automatic applied using the current AWS account
                                      manual: Commands necessary to modify AWS resources will be output to be run manually
      --path string                   The arn path for the ocm role and policies
      --permissions-boundary string   The ARN of the policy that is used to set the permissions boundary for the OCM role.
      --prefix string                 User-defined prefix for all generated AWS resources (default "ManagedOpenShift")
  -y, --yes                           Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa create oidc-config

```
Create OIDC config in a S3 bucket for the client AWS account and populates it to be compliant with OIDC protocol. It also creates a Secret in Secrets Manager containing the private key.

Usage:
  rosa create oidc-config [flags]

Aliases:
  oidc-config, oidcconfig

Examples:
  # Create OIDC config
	rosa create oidc-config

Flags:
  -h, --help              help for oidc-config
  -i, --interactive       Enable interactive mode.
      --managed           Indicates whether it is a Red Hat managed or unmanaged (Customer hosted) OIDC Configuration. (default true)
  -m, --mode string       How to perform the operation. Valid options are:
                          auto: Resource changes will be automatic applied using the current AWS account
                          manual: Commands necessary to modify AWS resources will be output to be run manually
  -o, --output string     Output format. Allowed formats are [json yaml]
      --prefix string     Prefix for the OIDC configuration, secret and provider.
      --raw-files         Creates OIDC config documents (Private RSA key, Discovery document, JSON Web Key Set) and saves locally for the client to create the configuration.
      --region string     Use a specific AWS region, overriding the AWS_REGION environment variable.
      --role-arn string   STS Role ARN with get secrets permission.
  -y, --yes               Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
```


### rosa create oidc-provider

```
Create OIDC provider for operators to authenticate against in an STS cluster.

Usage:
  rosa create oidc-provider [flags]

Aliases:
  oidc-provider, oidcprovider

Examples:
  # Create OIDC provider for cluster named "mycluster"
  rosa create oidc-provider --cluster=mycluster

Flags:
  -c, --cluster string          Name or ID of the cluster.
  -h, --help                    help for oidc-provider
  -i, --interactive             Enable interactive mode.
  -m, --mode string             How to perform the operation. Valid options are:
                                auto: Resource changes will be automatic applied using the current AWS account
                                manual: Commands necessary to modify AWS resources will be output to be run manually
      --oidc-config-id string   Registered OIDC configuration ID to retrieve its issuer URL. Not to be used alongside --cluster flag.
  -y, --yes                     Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa create operator-roles

```
Create cluster-specific operator IAM roles based on your cluster configuration.

Usage:
  rosa create operator-roles [flags]

Aliases:
  operator-roles, operatorroles

Examples:
  # Create default operator roles for cluster named "mycluster"
  rosa create operator-roles --cluster=mycluster

  # Create operator roles with a specific permissions boundary
  rosa create operator-roles -c mycluster --permissions-boundary arn:aws:iam::123456789012:policy/perm-boundary

Flags:
  -c, --cluster string                 Name or ID of the cluster.
  -f, --force-policy-creation          Forces creation of policies skipping compatibility check
  -h, --help                           help for operator-roles
      --hosted-cp                      Indicates whether to create the hosted control planes operator roles when using --prefix option.
  -i, --interactive                    Enable interactive mode.
  -m, --mode string                    How to perform the operation. Valid options are:
                                       auto: Resource changes will be automatic applied using the current AWS account
                                       manual: Commands necessary to modify AWS resources will be output to be run manually
      --oidc-config-id string          Registered OIDC configuration ID to add its issuer URL as the trusted relationship to the operator roles. Not to be used alongside --cluster flag.
      --permissions-boundary string    The ARN of the policy that is used to set the permissions boundary for the operator roles.
      --prefix string                  User-defined prefix for generated AWS operator policies. Not to be used alongside --cluster flag.
      --role-arn string                Installer role ARN supplied to retrieve operator policy prefix and path. Not to be used alongside --cluster flag.
      --route53-role-arn string        AWS IAM Role Arn with policy attached, associated with shared VPC. Grants permission necessary to handle route53 operations associated with a cross-account VPC. This flag deprecates '--shared-vpc-role-arn'.
      --vpc-endpoint-role-arn string   AWS IAM Role ARN with policy attached, associated with the shared VPC. Grants permissions necessary to communicate with and handle a Hosted Control Plane cross-account VPC.
  -y, --yes                            Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa create tuning-configs

```
Add a tuning config to a cluster.

Usage:
  rosa create tuning-configs [flags]

Aliases:
  tuning-configs, tuningconfig, tuningconfigs, tuning-config

Examples:
  # Add a tuning config with name "tuned1" and spec from a file "file1" to a cluster named "mycluster"
 rosa create tuning-config --name=tuned1 --spec-path=file1 --cluster=mycluster"

Flags:
  -c, --cluster string     Name or ID of the cluster.
  -h, --help               help for tuning-configs
  -i, --interactive        Enable interactive mode.
      --name string        Name of the tuning config to add.
      --spec-path string   Path of the file containing the spec section of the tuning config to add.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa create user-role

```
Create user role that allows OCM to verify that users creating a cluster have access to the current AWS account.

Usage:
  rosa create user-role [flags]

Aliases:
  user-role, userrole

Examples:
  # Create user roles
  rosa create user-role

  # Create user role with a specific permissions boundary
  rosa create user-role --permissions-boundary arn:aws:iam::123456789012:policy/perm-boundary

Flags:
  -h, --help                          help for user-role
  -i, --interactive                   Enable interactive mode.
  -m, --mode string                   How to perform the operation. Valid options are:
                                      auto: Resource changes will be automatic applied using the current AWS account
                                      manual: Commands necessary to modify AWS resources will be output to be run manually
      --path string                   The arn path for the user role and policies.
      --permissions-boundary string   The ARN of the policy that is used to set the permissions boundary for the user role.
      --prefix string                 User-defined prefix for ocm-user role (default "ManagedOpenShift")
  -y, --yes                           Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa delete

```
Delete a specific resource

Usage:
  rosa delete [command]

Aliases:
  delete, remove

Available Commands:
  account-roles          Delete Account Roles
  admin                  Deletes the admin user
  autoscaler             Delete autoscaler for cluster
  cluster                Delete cluster
  dns-domain             Delete DNS domain
  external-auth-provider Delete external authentication provider
  iamserviceaccount      Delete IAM role for Kubernetes service account
  idp                    Delete cluster IDPs
  image-mirror           Delete image mirror from a cluster
  ingress                Delete cluster ingress
  kubeletconfig          Delete a kubeletconfig from a cluster
  log-forwarder          Delete log forwarder
  machinepool            Delete machine pool
  ocm-role               Delete OCM role
  oidc-config            Delete OIDC Config
  oidc-provider          Delete OIDC Provider
  operator-roles         Delete Operator Roles
  tuning-configs         Delete tuning config
  upgrade                Cancel cluster upgrade
  user-role              Delete user role

Flags:
  -h, --help             help for delete
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa delete [command] --help" for more information about a command.
```


### rosa delete account-roles

```
Cleans up account roles from the current AWS account.

Usage:
  rosa delete account-roles [flags]

Aliases:
  account-roles, accountroles, accountrole, account-role

Examples:
  # Delete Account roles"
  rosa delete account-roles -p prefix

Flags:
      --classic                          Delete classic account roles
      --delete-hcp-shared-vpc-policies   Deletes the Hosted Control Plane shared vpc policies
  -h, --help                             help for account-roles
      --hosted-cp                        Delete Hosted Control Planes roles
  -m, --mode string                      How to perform the operation. Valid options are:
                                         auto: Resource changes will be automatic applied using the current AWS account
                                         manual: Commands necessary to modify AWS resources will be output to be run manually
  -p, --prefix string                    Prefix of the account roles to be deleted.
  -y, --yes                              Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete admin

```
Deletes the cluster-admin user used to login to the cluster

Usage:
  rosa delete admin [flags]

Examples:
  # Delete the admin user
  rosa delete admin --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for admin

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa delete autoscaler

```
Delete autoscaler configuration for a given cluster. Supported only on ROSA clusters with self-hosted Control Plane (Classic)

Usage:
  rosa delete autoscaler [flags]

Aliases:
  autoscaler, cluster-autoscaler

Examples:
  # Delete the autoscaler config for cluster named "mycluster"
  rosa delete autoscaler --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for autoscaler
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete cluster

```
Delete cluster.

Usage:
  rosa delete cluster [flags]

Examples:
  # Delete a cluster named "mycluster"
  rosa delete cluster --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
      --best-effort      Skips steps in the cluster destruction chain that are known to cause the cluster deletion process to fail. You should use this option with care and it is recommended that you manually check your AWS account for any resources that might be left over after using --best-effort.
  -w, --watch            Watch cluster uninstallation logs.
  -h, --help             help for cluster

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa delete dns-domain

```
Delete a specific DNS domain.

Usage:
  rosa delete dns-domain ID [flags]

Aliases:
  dns-domain, dnsdomain

Examples:
  # Delete a DNS domain with ID github-1
  rosa delete dns-domain github-1

Flags:
  -h, --help   help for dns-domain

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa delete external-auth-provider

```
Delete an external authentication provider from a cluster.

Usage:
  rosa delete external-auth-provider [flags]

Aliases:
  external-auth-provider, externalauthproviders, externalauthprovider, external-auth-providers

Examples:
  # Delete an external authentication provider named exauth-1
  rosa delete external-auth-provider exauth-1  --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for external-auth-provider

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa delete iamserviceaccount

```
Delete an IAM role that was created for a Kubernetes service account. This will remove the role and all attached policies.

Usage:
  rosa delete iamserviceaccount [flags]

Aliases:
  iamserviceaccount, iam-service-account

Examples:
  # Delete IAM role for service account
  rosa delete iamserviceaccount --cluster my-cluster \
    --name my-app \
    --namespace default

Flags:
  -c, --cluster string     Name or ID of the cluster.
  -h, --help               help for iamserviceaccount
  -i, --interactive        Enable interactive mode.
  -m, --mode string        How to perform the operation. Valid options are:
                           auto: Resource changes will be automatic applied using the current AWS account
                           manual: Commands necessary to modify AWS resources will be output to be run manually
      --name string        Name of the Kubernetes service account.
      --namespace string   Kubernetes namespace for the service account. (default "default")
      --role-name string   Name of the IAM role to delete (auto-detected if not specified).
  -y, --yes                Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete idp

```
Delete a specific identity provider for a cluster.

Usage:
  rosa delete idp ID [flags]

Aliases:
  idp, idps

Examples:
  # Delete an identity provider named github-1
  rosa delete idp github-1 --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for idp

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa delete image-mirror

```
Delete an image mirror configuration from a Hosted Control Plane cluster by ID.

Usage:
  rosa delete image-mirror [flags]

Aliases:
  image-mirror, image-mirrors

Examples:
  # Delete image mirror with ID "abc123" from cluster "mycluster"
  rosa delete image-mirror --cluster=mycluster abc123

  # Delete without confirmation prompt
  rosa delete image-mirror --cluster=mycluster abc123 --yes

  # Alternative: using the --id flag
  rosa delete image-mirror --cluster=mycluster --id=abc123

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for image-mirror
      --id string        ID of the image mirror configuration to delete
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm deletion

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa delete ingress

```
Delete the additional non-default application router for a cluster.

Usage:
  rosa delete ingress ID [flags]

Aliases:
  ingress, ingresses, route, routes

Examples:
  # Delete ingress with ID a1b2 from a cluster named 'mycluster'
  rosa delete ingress --cluster=mycluster a1b2

  # Delete secondary ingress using the sub-domain name
  rosa delete ingress --cluster=mycluster apps2

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for ingress

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa delete kubeletconfig

```
Delete a kubeletconfig from a cluster

Usage:
  rosa delete kubeletconfig [flags]

Aliases:
  kubeletconfig, kubelet-config

Examples:
  # Delete the KubeletConfig for ROSA Classic cluster 'foo'
  rosa delete kubeletconfig --cluster foo
  # Delete the KubeletConfig named 'bar' from cluster 'foo'
  rosa delete kubeletconfig --cluster foo --name bar


Flags:
  -c, --cluster string   Name or ID of the cluster.
  -y, --yes              Automatically answer yes to confirm operation.
      --name string      Name of the KubeletConfig (required for Hosted Control Plane clusters)
  -h, --help             help for kubeletconfig

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete log-forwarder

```
Delete a log forwarder from a cluster.

Usage:
  rosa delete log-forwarder -c <cluster-id> <log-forwarder-id> [flags]

Aliases:
  log-forwarder, log_forwarder, log-forwarder, logforwarder

Examples:
  # Delete log forwarder with ID 'example-id' from a cluster named 'mycluster-hcp'
  rosa delete log-forwarder --cluster=mycluster-hcp example-id

Flags:
  -c, --cluster string         Name or ID of the cluster.
  -h, --help                   help for log-forwarder
      --log-forwarder string   Log forwarder ID to delete
  -y, --yes                    Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete machinepool

```
Delete the additional machine pool from a cluster.

Usage:
  rosa delete machinepool ID [flags]

Aliases:
  machinepool, machinepools, machine-pool, machine-pools

Examples:
  # Delete machine pool with ID mp-1 from a cluster named 'mycluster'
  rosa delete machinepool --cluster=mycluster mp-1

Flags:
  -c, --cluster string       Name or ID of the cluster.
  -h, --help                 help for machinepool
      --machinepool string   Machine pool of the cluster to target
  -y, --yes                  Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete ocm-role

```
Delete OCM role from the current AWS organization

Usage:
  rosa delete ocm-role [flags]

Aliases:
  ocm-role, ocmrole

Examples:
 # Delete OCM role
rosa delete ocm-role --role-arn arn:aws:iam::123456789012:role/xxx-OCM-Role-1223456778

Flags:
  -h, --help              help for ocm-role
  -i, --interactive       Enable interactive mode.
  -m, --mode string       How to perform the operation. Valid options are:
                          auto: Resource changes will be automatic applied using the current AWS account
                          manual: Commands necessary to modify AWS resources will be output to be run manually
      --role-arn string   Role ARN to delete from the OCM organization account
  -y, --yes               Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete oidc-config

```
Cleans up OIDC config based on registered OIDC Config ID.

Usage:
  rosa delete oidc-config [flags]

Aliases:
  oidc-config, oidcconfig

Examples:
  # Delete OIDC config based on registered OIDC Config ID that has been supplied
	rosa delete oidc-config --oidc-config-id <oidc_config_id>

Flags:
  -h, --help                    help for oidc-config
  -i, --interactive             Enable interactive mode.
  -m, --mode string             How to perform the operation. Valid options are:
                                auto: Resource changes will be automatic applied using the current AWS account
                                manual: Commands necessary to modify AWS resources will be output to be run manually
      --oidc-config-id string   Registered ID for identification of OIDC config
  -y, --yes                     Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
```


### rosa delete oidc-provider

```
Cleans up OIDC provider of deleted STS cluster.

Usage:
  rosa delete oidc-provider [flags]

Aliases:
  oidc-provider, oidcprovider

Examples:
  # Delete OIDC provider for cluster named "mycluster"
  rosa delete oidc-provider --cluster=mycluster

Flags:
  -c, --cluster string          Name or ID of the cluster.
  -h, --help                    help for oidc-provider
  -m, --mode string             How to perform the operation. Valid options are:
                                auto: Resource changes will be automatic applied using the current AWS account
                                manual: Commands necessary to modify AWS resources will be output to be run manually
      --oidc-config-id string   Registered OIDC configuration ID to retrieve its issuer URL. Not to be used alongside --cluster flag.
  -y, --yes                     Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete operator-roles

```
Cleans up operator roles of deleted STS cluster.

Usage:
  rosa delete operator-roles [flags]

Aliases:
  operator-roles, operatorrole, operatorroles

Examples:
  # Delete Operator roles for cluster named "mycluster"
  rosa delete operator-roles --cluster=mycluster

Flags:
  -c, --cluster string                   Name or ID of the cluster.
      --delete-hcp-shared-vpc-policies   Deletes the Hosted Control Plane shared vpc policies
  -h, --help                             help for operator-roles
  -m, --mode string                      How to perform the operation. Valid options are:
                                         auto: Resource changes will be automatic applied using the current AWS account
                                         manual: Commands necessary to modify AWS resources will be output to be run manually
      --prefix string                    Operator role prefix, this flag needs to be used in case of reusable OIDC Config
  -y, --yes                              Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete tuning-configs

```
Delete a tuning config for a cluster.

Usage:
  rosa delete tuning-configs [flags]

Aliases:
  tuning-configs, tuningconfig, tuningconfigs, tuning-config

Examples:
  # Delete tuning config with name tuned1 from a cluster named 'mycluster'
  rosa delete tuning-config --cluster=mycluster tuned1

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for tuning-configs

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa delete upgrade

```
Cancel scheduled cluster upgrade

Usage:
  rosa delete upgrade [flags]

Aliases:
  upgrade, upgrades

Flags:
  -c, --cluster string       Name or ID of the cluster.
      --machinepool string   Machine pool of the cluster to target
  -y, --yes                  Automatically answer yes to confirm operation.
  -h, --help                 help for upgrade

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa delete user-role

```
Delete user role from the current AWS account

Usage:
  rosa delete user-role [flags]

Aliases:
  user-role, userrole

Examples:
 # Delete user role
rosa delete user-role --role-arn {prefix}-User-{username}-Role

Flags:
  -h, --help              help for user-role
  -i, --interactive       Enable interactive mode.
  -m, --mode string       How to perform the operation. Valid options are:
                          auto: Resource changes will be automatic applied using the current AWS account
                          manual: Commands necessary to modify AWS resources will be output to be run manually
      --role-arn string   Role ARN to delete from the user role from the AWS account
  -y, --yes               Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa describe

```
Show details of a specific resource

Usage:
  rosa describe [command]

Available Commands:
  access-request         Show details of an Access Request
  addon                  Show details of an add-on
  addon-installation     Show details of an add-on installation
  admin                  Show details of the cluster-admin user
  autoscaler             Show details of the autoscaler for a cluster
  break-glass-credential Show details of a break glass credential on a cluster
  cluster                Show details of a cluster
  external-auth-provider Show details of an external authentication provider on a cluster
  iamserviceaccount      Describe IAM role for Kubernetes service account
  ingress                Show details of the specified ingress within cluster
  kubeletconfig          Show details of a kubeletconfig for a cluster
  log-forwarder          Show details of a specific log forwarder used by a cluster
  machinepool            Show details of a machine pool on a cluster
  tuning-configs         Show details of tuning config
  upgrade                Show details of an upgrade

Flags:
  -h, --help             help for describe
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa describe [command] --help" for more information about a command.
```


### rosa describe access-request

```
Show details of an Access Request

Usage:
  rosa describe access-request [flags]

Aliases:
  access-request, accessrequest

Examples:
  # Describe an Access Request wit id <access_request_id>
  rosa describe access-request --id <access_request_id>
  

Flags:
  -h, --help            help for access-request
      --id string       ID of the Access Request. (required).
  -o, --output string   Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe addon

```
Show details of an add-on

Usage:
  rosa describe addon ID [flags]

Aliases:
  addon, add-on

Examples:
  # Describe an add-on named "codeready-workspaces"
  rosa describe addon codeready-workspaces

Flags:
  -h, --help   help for addon

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe addon-installation

```
Show details of an add-on installation

Usage:
  rosa describe addon-installation clusterID AddonInstallationID [flags]

Aliases:
  addon-installation, add-on-installation

Examples:
  # Describe the 'bar' add-on installation on cluster 'foo'
  rosa describe addon-installation --cluster foo --addon bar

Flags:
      --addon string     Name or ID of the addon installation (required).
  -c, --cluster string   Name or ID of the cluster to list the add-ons of (required).
  -h, --help             help for addon-installation

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe admin

```
Show details of the cluster-admin user and a command to login to the cluster

Usage:
  rosa describe admin [flags]

Examples:
  # Describe cluster-admin user of a cluster named mycluster
  rosa describe admin -c mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for admin

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe autoscaler

```
Describes the configuration for cluster's Cluster Auto-scaler. Supported on ROSA clusters service-hosted (HCP) with self-hosted (Classic) control planes.

Usage:
  rosa describe autoscaler [flags]

Aliases:
  autoscaler, cluster-autoscaler

Examples:
 # Describe the autoscaler for cluster 'foo'
rosa describe autoscaler --cluster foo

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for autoscaler
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
```


### rosa describe break-glass-credential

```
Show details of a break glass credential on a cluster.

Usage:
  rosa describe break-glass-credential [flags]

Aliases:
  break-glass-credential, break-glass-credentials, breakglasscredential, breakglasscredentials

Examples:
  # Show details of a break glass credential with ID "12345" on a cluster named "mycluster"
  rosa describe break-glass-credential 12345 --cluster=mycluster 

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -o, --output string    Output format. Allowed formats are [json yaml]
      --id string        Id for the break glass credential of the cluster to target
      --kubeconfig       Retrieve the kubeconfig from the break glass credential
  -h, --help             help for break-glass-credential

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe cluster

```
Show details of a cluster

Usage:
  rosa describe cluster [flags]

Examples:
  # Describe a cluster named "mycluster"
  rosa describe cluster --cluster=mycluster

Flags:
  -c, --cluster string             Name or ID of the cluster.
      --get-role-policy-bindings   List the attached policies for the sts roles
  -h, --help                       help for cluster
  -o, --output string              Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe external-auth-provider

```
Show details of an external authentication provider on a cluster.

Usage:
  rosa describe external-auth-provider [flags]

Aliases:
  external-auth-provider, externalauthproviders, externalauthprovider, external-auth-providers

Examples:
  # Show details of an external authentication provider named "exauth" on a cluster named "mycluster"
  rosa describe external-auth-provider exauth --cluster=mycluster 

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -o, --output string    Output format. Allowed formats are [json yaml]
      --name string      Name for the external authentication provider of the cluster to target
  -h, --help             help for external-auth-provider

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe iamserviceaccount

```
Show detailed information about an IAM role that was created for a Kubernetes service account, including trust policy and attached permissions.

Usage:
  rosa describe iamserviceaccount [flags]

Aliases:
  iamserviceaccount, iam-service-account

Examples:
  # Describe IAM role for service account
  rosa describe iamserviceaccount --cluster my-cluster \
    --name my-app \
    --namespace default

Flags:
  -c, --cluster string     Name or ID of the cluster.
  -h, --help               help for iamserviceaccount
  -i, --interactive        Enable interactive mode.
      --name string        Name of the Kubernetes service account.
      --namespace string   Kubernetes namespace for the service account. (default "default")
  -o, --output string      Output format. Allowed formats are [json yaml]
      --role-name string   Name of the IAM role to describe (auto-detected if not specified).

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
```


### rosa describe ingress

```
Show details of the specified ingress within cluster

Usage:
  rosa describe ingress [flags]

Examples:
rosa describe ingress <ingress_id> -c mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for ingress
      --ingress string   Ingress of the cluster to target
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe kubeletconfig

```
Show details of a kubeletconfig for a cluster

Usage:
  rosa describe kubeletconfig [flags]

Aliases:
  kubeletconfig, kubelet-config

Examples:
  # Describe the custom kubeletconfig for ROSA Classic cluster 'foo'
  rosa describe kubeletconfig --cluster foo
  # Describe the custom kubeletconfig named 'bar' for cluster 'foo'
  rosa describe kubeletconfig --cluster foo --name bar


Flags:
  -c, --cluster string   Name or ID of the cluster.
  -o, --output string    Output format. Allowed formats are [json yaml]
      --name string      Name of the KubeletConfig (required for Hosted Control Plane clusters)
  -h, --help             help for kubeletconfig

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe log-forwarder

```
Show details of a specific log forwarder used by a cluster

Usage:
  rosa describe log-forwarder [flags]

Examples:
rosa describe log-forwarder <log_fwd_id> -c mycluster-hcp

Flags:
  -c, --cluster string         Name or ID of the cluster.
  -h, --help                   help for log-forwarder
      --log-forwarder string   Log forwarder ID of the cluster to target
  -o, --output string          Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
```


### rosa describe machinepool

```
Show details of a machine pool on a cluster.

Usage:
  rosa describe machinepool [flags]

Aliases:
  machinepool, machine-pool

Examples:
  # Show details of a machine pool named "mymachinepool" on a cluster named "mycluster"
  rosa describe machinepool --cluster=mycluster --machinepool=mymachinepool

Flags:
  -c, --cluster string       Name or ID of the cluster.
  -h, --help                 help for machinepool
      --machinepool string   Machine pool of the cluster to target
  -o, --output string        Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe tuning-configs

```
Show details of a tuning config for a cluster.

Usage:
  rosa describe tuning-configs [flags]

Aliases:
  tuning-configs, tuningconfig, tuningconfigs, tuning-config

Examples:
  # Describe the 'tuned1' tuned config on cluster 'foo'
  rosa describe tuning-config --cluster foo tuned1

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for tuning-configs
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa describe upgrade

```
Show details of an upgrade

Usage:
  rosa describe upgrade [flags]

Aliases:
  upgrade, appliance, upgrades

Examples:
  # Describe an upgrade-policy"
  rosa describe upgrade

Flags:
  -c, --cluster string       Name or ID of the cluster.
      --machinepool string   Machine pool of the cluster to target
  -y, --yes                  Automatically answer yes to confirm operation.
  -h, --help                 help for upgrade

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa download

```
Download necessary tools for using your cluster

Usage:
  rosa download [command]

Available Commands:
  openshift-client Download OpenShift client tools
  rosa-client      Download ROSA client tools

Flags:
  -h, --help   help for download

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa download [command] --help" for more information about a command.
```


### rosa download openshift-client

```
Downloads to latest compatible version of the OpenShift client tools.

Usage:
  rosa download openshift-client [flags]

Aliases:
  openshift-client, oc, openshift

Examples:
  # Download oc client tools
  rosa download oc

Flags:
  -h, --help   help for openshift-client

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa download rosa-client

```
Downloads to latest compatible version of the ROSA client tools.

Usage:
  rosa download rosa-client [flags]

Aliases:
  rosa-client, rosa

Examples:
  # Download rosa client tools
  rosa download rosa

Flags:
  -h, --help   help for rosa-client

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa edit

```
Edit a specific resource

Usage:
  rosa edit [command]

Aliases:
  edit, update

Available Commands:
  addon           Edit add-on installation parameters on cluster
  autoscaler      Edit the autoscaler of a cluster
  cluster         Edit cluster
  image-mirror    Edit image mirror for a cluster
  ingress         Edit a cluster ingress (load balancer)
  kubeletconfig   Edit a kubeletconfig for a cluster
  log-forwarder   Edit a log forwarder for a cluster
  machinepool     Edit machine pool
  tuning-configs  Edit tuning config

Flags:
  -h, --help             help for edit
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa edit [command] --help" for more information about a command.
```


### rosa edit addon

```
Edit the parameters on installed Red Hat managed add-ons on a cluster

Usage:
  rosa edit addon ID [flags]

Aliases:
  addon, addons, add-on, add-ons

Examples:
  # Edit the parameters of the Red Hat OpenShift logging operator add-on installation
  rosa edit addon --cluster=mycluster cluster-logging-operator

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for addon

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa edit autoscaler

```
    Updates the configuration for cluster's Cluster Auto-scaler. Supported on ROSA clusters service-hosted (HCP) with self-hosted (Classic) control planes.

Usage:
  rosa edit autoscaler [flags]

Aliases:
  autoscaler, cluster-autoscaler

Examples:
  # Interactively edit an autoscaler to a cluster named "mycluster"
  rosa edit autoscaler --cluster=mycluster --interactive

  # Edit a cluster-autoscaler to skip nodes with local storage
  rosa edit autoscaler --cluster=mycluster --skip-nodes-with-local-storage

  # Edit a cluster-autoscaler with log verbosity of '3'
  rosa edit autoscaler --cluster=mycluster --log-verbosity 3

  # Edit a cluster-autoscaler with total CPU constraints
  rosa edit autoscaler --cluster=mycluster --min-cores 10 --max-cores 100

Flags:
  -c, --cluster string                           Name or ID of the cluster.
  -i, --interactive                              Enable interactive mode.
      --balance-similar-node-groups              Identify node groups with the same instance type and label set, and aim to balance respective sizes of those node groups. Only supported for self-hosted (Classic) control plane clusters.
      --skip-nodes-with-local-storage            If true cluster autoscaler will never delete nodes with pods with local storage, e.g. EmptyDir or HostPath. Only supported for self-hosted (Classic) control plane clusters.
      --log-verbosity int                        Autoscaler log level. Default is 1, 4 is a good option when trying to debug the autoscaler. Only supported for self-hosted (Classic) control plane clusters. (default 1)
      --max-pod-grace-period int                 Gives pods graceful termination time before scaling down, measured in seconds. (default 600)
      --pod-priority-threshold int               The priority that a pod must exceed to cause the cluster autoscaler to deploy additional nodes. Expects an integer, can be negative. (default -10)
      --ignore-daemonsets-utilization            Should cluster-autoscaler ignore DaemonSet pods when calculating resource utilization for scaling down. Only supported for self-hosted (Classic) control plane clusters.
      --max-node-provision-time string           Maximum time cluster-autoscaler waits for node to be provisioned. Expects string comprised of an integer and time unit (ns|us|µs|ms|s|m|h), examples: 20m, 1h. (default "15m")
      --balancing-ignored-labels strings         A comma-separated list of label keys that cluster autoscaler should ignore when considering node group similarity. Only supported for self-hosted (Classic) control plane clusters.
      --max-nodes-total int                      Total amount of nodes that can exist in the cluster, including non-scaled nodes.
      --min-cores int                            Minimum limit for the amount of cores to deploy in the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --max-cores int                            Maximum limit for the amount of cores to deploy in the cluster. Only supported for self-hosted (Classic) control plane clusters. (default 11520)
      --min-memory int                           Minimum limit for the amount of memory, in GiB, in the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --max-memory int                           Maximum limit for the amount of memory, in GiB, in the cluster. Only supported for self-hosted (Classic) control plane clusters. (default 230400)
      --gpu-limit stringArray                    Limit GPUs consumption. It should be comprised of 3 values separated with commas: the GPU hardware type, a minimal count for that type and a maximal count for that type. This option can be repeated multiple times in order to apply multiple restrictions for different GPU types. Only supported for self-hosted (Classic) control plane clusters. For example: --gpu-limit nvidia.com/gpu,0,10 --gpu-limit amd.com/gpu,1,5
      --scale-down-enabled                       Should cluster-autoscaler be able to scale down the cluster. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-unneeded-time string          Increasing value will make nodes stay up longer, waiting for pods to be scheduled while decreasing value will make nodes be deleted sooner. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-utilization-threshold float   Node utilization level, defined as sum of requested resources divided by capacity, below which a node can be considered for scale down. Value should be between 0 and 1. Only supported for self-hosted (Classic) control plane clusters. (default 0.5)
      --scale-down-delay-after-add string        After a scale-up, consider scaling down only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-delay-after-delete string     After a scale-down, consider scaling down again only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
      --scale-down-delay-after-failure string    After a failing scale-down, consider scaling down again only after this amount of time. Only supported for self-hosted (Classic) control plane clusters.
  -h, --help                                     help for autoscaler

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa edit cluster

```
Edit cluster.

Usage:
  rosa edit cluster [flags]

Examples:
  # Edit a cluster named "mycluster" to make it private
  rosa edit cluster -c mycluster --private

  # Edit all options interactively
  rosa edit cluster -c mycluster --interactive

Flags:
  -c, --cluster string                                         Name or ID of the cluster.
  -y, --yes                                                    Automatically answer yes to confirm operation.
      --enable-delete-protection                               Toggle cluster deletion protection against accidental cluster deletion.
      --private                                                Restrict master API endpoint to direct, private connectivity.
      --disable-workload-monitoring                            Enables you to monitor your own projects in isolation from Red Hat Site Reliability Engineer (SRE) platform metrics. Not supported for Hosted Control Plane clusters.
      --http-proxy string                                      A proxy URL to use for creating HTTP connections outside the cluster. The URL scheme must be http.
      --https-proxy string                                     A proxy URL to use for creating HTTPS connections outside the cluster.
      --no-proxy strings                                       A comma-separated list of destination domain names, domains, IP addresses or other network CIDRs to exclude proxying.
      --additional-trust-bundle-file string                    A file contains a PEM-encoded X.509 certificate bundle that will be added to the nodes' trusted certificate store.
      --audit-log-arn string                                   The ARN of the role that is used to forward audit logs to AWS CloudWatch.
      --autonode string                                        Configure AutoNode for the cluster. Valid values are: enabled
      --autonode-iam-role-arn string                           The AWS ARN of the IAM Role that has permissions for AutoNode
      --additional-allowed-principals strings                  A comma-separated list of additional allowed principal ARNs to be added to the Hosted Control Plane's VPC Endpoint Service to enable additional VPC Endpoint connection requests to be automatically accepted.
      --registry-config-allowed-registries strings             A comma-separated list of registries for which image pull and push actions are allowed.
      --registry-config-insecure-registries strings            A comma-separated list of registries which do not have a valid TLS certificate or only support HTTP connections.
      --registry-config-blocked-registries strings             A comma-separated list of registries for which image pull and push actions are denied.
      --registry-config-allowed-registries-for-import string   Limits the container image registries from which normal users can import images. The format should be a comma-separated list of 'domainName:insecure'. 'domainName' specifies a domain name for the registry. 'insecure' indicates whether the registry is secure or insecure.
      --registry-config-additional-trusted-ca string           A json file containing the registry hostname as the key, and the PEM-encoded certificate as the value, for each additional registry CA to trust.
      --billing-account string                                 Account ID used for billing subscriptions purchased through the AWS console for ROSA
      --network-type string                                    Migrate a cluster's network type from OpenShiftSDN to OVN-Kubernetes
      --ovn-internal-subnets string                            OVN-Kubernetes internal subnet configuration for migrating 'network-type' from OpenShiftSDN -> OVN-Kubernetes. Must be supplied as a string=value pair with any of 'join', 'transit', 'masquerade' followed by a CIDR. 
                                                               Example: '--ovn-internal-subnets="join=192.168.255.0/24,transit=192.168.255.0/24,masquerade=192.168.255.0/24"'
      --channel-group string                                   Changes the channel group used for cluster versions. Channel group is the name of the channel where this image belongs, for example "stable" or "eus".
  -h, --help                                                   help for cluster

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa edit image-mirror

```
Edit an existing image mirror configuration for a Hosted Control Plane cluster by ID. Only the mirrors list can be updated.

Usage:
  rosa edit image-mirror [flags]

Aliases:
  image-mirror, image-mirrors

Examples:
  # Update mirrors for image mirror with ID "abc123" on cluster "mycluster"
  rosa edit image-mirror --cluster=mycluster abc123 \
    --mirrors=mirror.corp.com/team,backup.corp.com/team,new-mirror.corp.com/team

  # Alternative: using the --id flag
  rosa edit image-mirror --cluster=mycluster --id=abc123 \
    --mirrors=mirror.corp.com/team,backup.corp.com/team,new-mirror.corp.com/team

Flags:
  -c, --cluster string    Name or ID of the cluster.
  -h, --help              help for image-mirror
      --id string         ID of the image mirror configuration to edit
      --mirrors strings   New list of mirror registries (comma-separated, required). This will replace the existing mirrors.
      --profile string    Use a specific AWS profile from your credential file.
      --region string     Use a specific AWS region, overriding the AWS_REGION environment variable.
      --type string       Type of image mirror (default: digest) (default "digest")

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
  -i, --interactive    Enable interactive mode.
  -y, --yes            Automatically answer yes to confirm operation.
```


### rosa edit ingress

```
Edit a cluster ingress for a cluster.

Usage:
  rosa edit ingress ID [flags]

Aliases:
  ingress, route

Examples:
  # Make additional ingress with ID 'a1b2' private on a cluster named 'mycluster'
  rosa edit ingress --private --cluster=mycluster a1b2

  # Update the router selectors for the additional ingress with ID 'a1b2'
  rosa edit ingress --label-match=foo=bar --cluster=mycluster a1b2

  # Update the default ingress using the sub-domain identifier
  rosa edit ingress --private=false --cluster=mycluster apps

  # Update the load balancer type of the apps2 ingress 
  rosa edit ingress --lb-type=nlb --cluster=mycluster apps2

Flags:
  -c, --cluster string                      Name or ID of the cluster.
      --component-routes string             Component routes settings. Available keys [oauth, console, downloads]. For each key a pair of hostname and tlsSecretRef is expected to be supplied. Format should be a comma separate list 'oauth: hostname=example-hostname;tlsSecretRef=example-secret-ref,downloads:...
      --excluded-namespaces string          Excluded namespaces for ingress. Format should be a comma-separated list 'value1, value2...'. If no values are specified, all namespaces will be exposed.
  -h, --help                                help for ingress
      --label-match string                  Alias to 'route-selector' flag.
      --lb-type string                      Type of Load Balancer. Options are classic,nlb.
      --namespace-ownership-policy string   Namespace Ownership Policy for ingress. Options are Strict,InterNamespaceAllowed. Default is 'Strict'.
      --private                             Restrict application route to direct, private connectivity.
      --route-selector string               Route Selector for ingress. Format should be a comma-separated list of 'key=value'. If no label is specified, all routes will be exposed on both routers. For legacy ingress support these are inclusion labels, otherwise they are treated as exclusion label.
      --wildcard-policy string              Wildcard Policy for ingress. Options are WildcardsDisallowed,WildcardsAllowed. Default is 'WildcardsDisallowed'.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa edit kubeletconfig

```
Edit a kubeletconfig for a cluster

Usage:
  rosa edit kubeletconfig [flags]

Aliases:
  kubeletconfig, kubelet-config

Examples:
  # Edit a KubeletConfig to have a pod-pids-limit of 10000
  rosa edit kubeletconfig --cluster=mycluster --pod-pids-limit=10000
  # Edit a KubeletConfig named 'bar' to have a pod-pids-limit of 10000
  rosa edit kubeletconfig --cluster=mycluster --name=bar --pod-pids-limit=10000
  

Flags:
  -c, --cluster string       Name or ID of the cluster.
  -i, --interactive          Enable interactive mode.
      --pod-pids-limit int   Sets the requested pod_pids_limit for this KubeletConfig.
      --name string          Name of the KubeletConfig (required for Hosted Control Plane clusters)
  -h, --help                 help for kubeletconfig

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa edit log-forwarder

```
Edit a log forwarder configuration for a cluster. A cluster ID must be provided, as well as a valid log forwarder ID on that cluster. For example: 'rosa edit log-forwarder -c my-cluster-1 2n4b8f8ai80cs6kmjmdgqlqplh73r411'

Usage:
  rosa edit log-forwarder -c <cluster-id> <log-fwd-id> --log-fwd-config <path-to-config> [flags]

Flags:
  -c, --cluster string          Name or ID of the cluster.
      --log-fwd-config string   Path to YAML file containing log forwarder configuration
  -h, --help                    help for log-forwarder

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa edit machinepool

```
Edit machine pools on a cluster.

Usage:
  rosa edit machinepool ID [flags]

Aliases:
  machinepool, machinepools, machine-pool, machine-pools

Examples:
  # Set 4 replicas on machine pool 'mp1' on cluster 'mycluster'
	rosa edit machinepool --replicas=4 --cluster=mycluster mp1
	# Enable autoscaling and Set 3-5 replicas on machine pool 'mp1' on cluster 'mycluster'
	rosa edit machinepool --enable-autoscaling --min-replicas=3 --max-replicas=5 --cluster=mycluster mp1
	# Set the node drain grace period to 1 hour on machine pool 'mp1' on cluster 'mycluster'
	rosa edit machinepool --node-drain-grace-period="1 hour" --cluster=mycluster mp1

Flags:
      --autorepair                       Select auto-repair behaviour for a machinepool in a hosted cluster. (default true)
  -c, --cluster string                   Name or ID of the cluster.
      --enable-autoscaling               Enable autoscaling for the machine pool.
  -h, --help                             help for machinepool
      --kubelet-configs string           Name of the kubelet config to be applied to the machine pool.  A single kubelet config is allowed. Kubelet config must already exist. This will overwrite any modifications made to node kubelet configs on an ongoing basis.
      --labels string                    Labels for machine pool. Format should be a comma-separated list of 'key=value'. This list will overwrite any modifications made to node labels on an ongoing basis.
      --machinepool string               Machine pool of the cluster to target
      --max-replicas int                 Maximum number of machines for the machine pool.
      --max-surge string                 The maximum number of nodes that can be provisioned above the desired number of nodes in the machinepool during the upgrade. It can be an absolute number i.e. 1, or a percentage i.e. '20%'.
      --max-unavailable string           The maximum number of nodes in the machinepool that can be unavailable during the upgrade. It can be an absolute number i.e. 1, or a percentage i.e. '20%'.
      --min-replicas int                 Minimum number of machines for the machine pool.
      --node-drain-grace-period string   You may set a grace period for how long Pod Disruption Budget-protected workloads will be respected when the NodePool is being replaced or upgraded.
                                         After this grace period, all remaining workloads will be forcibly evicted.
                                         Valid value is from 0 to 1 week (10080 minutes), and the supported units are 'minute|minutes' or 'hour|hours'. 0 or empty value means that the NodePool can be drained without any time limitations.
                                         This flag is only supported for Hosted Control Planes.
  -o, --output string                    Output format. Allowed formats are [json yaml]
      --replicas int                     Count of machines for this machine pool.
      --taints string                    Taints for machine pool. Format should be a comma-separated list of 'key=value:ScheduleType'. This list will overwrite any modifications made to node taints on an ongoing basis.
      --tuning-configs string            Name of the tuning configs to be applied to the machine pool. Format should be a comma-separated list. Tuning config must already exist. This list will overwrite any modifications made to node tuning configs on an ongoing basis.
  -y, --yes                              Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa edit tuning-configs

```
Edit a tuning config for a cluster.

Usage:
  rosa edit tuning-configs [flags]

Aliases:
  tuning-configs, tuningconfig, tuningconfigs, tuning-config

Examples:
  # Update the tuning config with name 'tuning-1' with the spec defined in file1
  rosa edit tuning-config --cluster=mycluster tuning-1 --spec-path file1

Flags:
  -c, --cluster string     Name or ID of the cluster.
  -h, --help               help for tuning-configs
      --spec-path string   Path of the file containing the new spec section of the tuning config to edit.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


## rosa grant

```
Grant role to a specific resource

Usage:
  rosa grant [command]

Available Commands:
  user        Grant user access to cluster

Flags:
  -h, --help             help for grant
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa grant [command] --help" for more information about a command.
```


### rosa grant user

```
Grant user access to cluster under a specific role

Usage:
  rosa grant user ROLE [flags]

Aliases:
  user, role

Examples:
  # Add cluster-admin role to a user
  rosa grant user cluster-admin --user=myusername --cluster=mycluster

  # Grant dedicated-admins role to a user
  rosa grant user dedicated-admin --user=myusername --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for user
  -u, --user string      Username to grant the role to (required).

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa init

```
Applies templates to support Red Hat OpenShift Service on AWS. If you are not
yet logged in to OCM, it will prompt you for credentials.

Usage:
  rosa init [flags]

Examples:
  # Configure your AWS account to allow IAM (non-STS) ROSA clusters
  rosa init

  # Configure a new AWS account using pre-existing OCM credentials
  rosa init --token=$OFFLINE_ACCESS_TOKEN

Flags:
      --delete                 Deletes stack template applied to your AWS account during the 'init' command.
      --disable-scp-checks     Indicates if cloud permission checks are disabled when attempting installation of the cluster.
      --client-id string       OpenID client identifier. The default value is 'cloud-services'.
      --client-secret string   OpenID client secret.
      --govcloud               Uses the FedRAMP High OpenShift Cluster Manager API for creating clusters in AWS GovCloud regions
      --insecure               Enables insecure communication with the server. This disables verification of TLS certificates and host names.
      --region string          Use a specific AWS region, overriding the AWS_REGION environment variable.
      --scope strings          OpenID scope. If this option is used it will completely replace the default scopes. Can be repeated multiple times to specify multiple scopes. (default [openid])
  -t, --token string           Access or refresh token generated from https://console.redhat.com/openshift/token/rosa.
      --token-url string       OpenID token URL. The default value is 'https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token'.
      --use-auth-code          Login using OAuth Authorization Code. This should be used for most cases where a browser is available. See --use-device-code for remote hosts and containers.
      --use-device-code        Login using OAuth Device Code. This should only be used for remote hosts and containers where browsers are not available. See --use-auth-code for all other scenarios.
      --profile string         Use a specific AWS profile from your credential file.
  -y, --yes                    Automatically answer yes to confirm operation.
  -h, --help                   help for init

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa install

```
Installs a resource into a cluster

Usage:
  rosa install [command]

Available Commands:
  addon       Install add-ons on cluster

Flags:
  -h, --help             help for install
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa install [command] --help" for more information about a command.
```


### rosa install addon

```
Install Red Hat managed add-ons on a cluster

Usage:
  rosa install addon ID [flags]

Aliases:
  addon, addons, add-on, add-ons

Examples:
  # Add the CodeReady Workspaces add-on installation to the cluster
  rosa install addon --cluster=mycluster codeready-workspaces

Flags:
      --billing-model string              Set the billing model to be used for the addon installation resource (default "standard")
      --billing-model-account-id string   Account ID of associated billing model for the addon installation resource
  -c, --cluster string                    Name or ID of the cluster.
  -h, --help                              help for addon
  -y, --yes                               Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa link

```
Link OCM role to specific OCM organization

Usage:
  rosa link [command]

Aliases:
  link, associate

Available Commands:
  ocm-role    Link OCM role to specific OCM organization.
  user-role   Link user role to specific OCM account.

Flags:
  -h, --help             help for link
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa link [command] --help" for more information about a command.
```


### rosa link ocm-role

```
Link OCM role to specific OCM organization before you create your cluster.

Usage:
  rosa link ocm-role [flags]

Aliases:
  ocm-role, ocmrole

Examples:
 # Link OCM role
  rosa link ocm-role --role-arn arn:aws:iam::123456789012:role/ManagedOpenshift-OCM-Role

Flags:
  -h, --help                     help for ocm-role
  -i, --interactive              Enable interactive mode.
      --organization-id string   OCM organization id to associate the ocm role ARN
      --role-arn string          Role ARN to associate the OCM organization account to
  -y, --yes                      Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa link user-role

```
Link user role to specific OCM account before create your cluster.

Usage:
  rosa link user-role [flags]

Aliases:
  user-role, userrole

Examples:
 # Link user roles
  rosa link user-role --role-arn arn:aws:iam::{accountid}:role/{prefix}-User-{username}-Role

Flags:
      --account-id string   OCM account id to associate the user role ARN
  -h, --help                help for user-role
  -i, --interactive         Enable interactive mode.
      --role-arn string     Role ARN to associate the OCM account to
  -y, --yes                 Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa list

```
List all resources of a specific type

Usage:
  rosa list [command]

Available Commands:
  access-request          List Access Requests
  account-roles           List account roles and policies
  addons                  List add-on installations
  break-glass-credentials List break glass credential
  clusters                List clusters
  dns-domain              List DNS Domains
  external-auth-providers List external authentication provider
  gates                   List available OCP Gates
  iamserviceaccounts      List IAM roles for Kubernetes service accounts
  idps                    List cluster IDPs
  image-mirrors           List cluster image mirrors
  ingresses               List cluster Ingresses
  instance-types          List Instance types
  kubeletconfigs          List kubeletconfigs
  log-forwarders          List cluster log forwarders
  machinepools            List cluster machine pools
  ocm-roles               List ocm roles
  oidc-config             List OIDC Configuration resources
  oidc-providers          List OIDC providers
  operator-roles          List operator roles and policies
  regions                 List available regions
  tuning-configs          List tuning configs
  upgrades                List available cluster upgrades
  user-roles              List user roles
  users                   List cluster users
  versions                List available versions

Flags:
  -h, --help             help for list
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa list [command] --help" for more information about a command.
```


### rosa list access-request

```
List Access Requests in Pending or Approved status. If '--cluster' flag is used, list all Access Requests in any status for the specified cluster.

Usage:
  rosa list access-request [flags]

Aliases:
  access-request, accessrequest, accessrequests, access-requests

Examples:
  # List all Access Requests for cluster 'foo'
  rosa list access-request --cluster foo
  

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for access-request
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list account-roles

```
List account roles and policies for the current AWS account.

Usage:
  rosa list account-roles [flags]

Aliases:
  account-roles, accountrole, account-role, accountroles

Examples:
  # List all account roles
  rosa list account-roles

Flags:
      --version string   List only account-roles that are associated with the given version.
  -o, --output string    Output format. Allowed formats are [json yaml]
  -h, --help             help for account-roles

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list addons

```
List add-ons installed on a cluster.

Usage:
  rosa list addons [flags]

Aliases:
  addons, addon, add-ons, add-on

Examples:
  # List all add-on installations on a cluster named "mycluster"
  rosa list addons --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster to list the add-ons of (required).
  -h, --help             help for addons
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list break-glass-credentials

```
List break glass credential for a cluster.

Usage:
  rosa list break-glass-credentials [flags]

Aliases:
  break-glass-credentials, break-glass-credential, breakglasscredential, breakglasscredentials

Examples:
  # List all break glass credentials for a cluster named 'mycluster'"
  rosa list break-glass-credentials -c mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for break-glass-credentials
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list clusters

```
List clusters.

Usage:
  rosa list clusters [flags]

Aliases:
  clusters, cluster

Examples:
  # List all clusters
  rosa list clusters

Flags:
  -o, --output string             Output format. Allowed formats are [json yaml]
  -a, --all                       List all clusters across different AWS accounts under the same Red Hat organization
      --account-role-arn string   List all clusters using the account role identified by the ARN
  -h, --help                      help for clusters

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list dns-domain

```
List DNS Domains

Usage:
  rosa list dns-domain [flags]

Aliases:
  dns-domain, dnsdomain, dnsdomains, dns-domain, dns-domains

Examples:
  # List all DNS Domains tied to your organization ID"
  rosa list dns-domain

Flags:
  -a, --all             List all DNS domains (default lists just user defined).
  -h, --help            help for dns-domain
      --hosted-cp       Filter to list only DNS Domains used for Hosted Control Plane clusters
  -o, --output string   Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list external-auth-providers

```
List external authentication provider for a cluster.

Usage:
  rosa list external-auth-providers [flags]

Aliases:
  external-auth-providers, externalauthproviders, externalauthprovider, external-auth-provider

Examples:
  # List all external authentication providers for a cluster named 'mycluster'"
  rosa list external-auth-provider -c mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for external-auth-providers
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list gates

```
List available OCP Gates for a specific OCP release or by cluster upgrade version

Usage:
  rosa list gates [flags]

Aliases:
  gates, gates

Examples:
  # List all OCP gates for OCP version
  rosa list gates --version 4.9

  # List all STS gates for OCP version
  rosa list gates --gate sts --version 4.9

  # List all OCP gates for OCP version
  rosa list gates --gate ocp --version 4.9

  # List available gates for cluster upgrade version
  rosa list gates -c <cluster_id> --version 4.9.15

Flags:
  -c, --cluster string   Name or ID of the cluster.
      --gate string      Gate type
  -h, --help             help for gates
  -o, --output string    Output format. Allowed formats are [json yaml]
      --version string   OCP version

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list iamserviceaccounts

```
List IAM roles that were created for Kubernetes service accounts using OpenID Connect (OIDC) identity federation.

Usage:
  rosa list iamserviceaccounts [flags]

Aliases:
  iamserviceaccounts, iam-service-accounts, iamserviceaccount, iam-service-account

Examples:
  # List IAM roles for service accounts
  rosa list iamserviceaccounts --cluster my-cluster

Flags:
  -c, --cluster string     Name or ID of the cluster.
  -h, --help               help for iamserviceaccounts
      --namespace string   Namespace to filter service account roles by.
  -o, --output string      Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list idps

```
List identity providers for a cluster.

Usage:
  rosa list idps [flags]

Aliases:
  idps, idp

Examples:
  # List all identity providers on a cluster named "mycluster"
  rosa list idps --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for idps
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list image-mirrors

```
List image mirror configurations for a Hosted Control Plane cluster.

Usage:
  rosa list image-mirrors [flags]

Aliases:
  image-mirrors, image-mirror

Examples:
  # List all image mirrors on a cluster named "mycluster"
  rosa list image-mirrors --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for image-mirrors
  -o, --output string    Output format. Allowed formats are [json yaml]
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa list ingresses

```
List API and ingress endpoints for a cluster.

Usage:
  rosa list ingresses [flags]

Aliases:
  ingresses, route, routes, ingress

Examples:
  # List all routes on a cluster named "mycluster"
  rosa list ingresses --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for ingresses
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list instance-types

```
List Instance types that are available for use with ROSA.

Usage:
  rosa list instance-types [flags]

Aliases:
  instance-types, instancetypes

Examples:
  # List all instance types
	rosa list instance-types

Flags:
      --external-id string   An optional unique identifier that might be required when you assume a role in another account.
  -h, --help                 help for instance-types
      --hosted-cp            Enable the use of Hosted Control Planes
  -o, --output string        Output format. Allowed formats are [json yaml]
      --region string        Use a specific AWS region, overriding the AWS_REGION environment variable.
      --role-arn string      STS Role ARN with get secrets permission.
  -y, --yes                  Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
```


### rosa list kubeletconfigs

```
List kubeletconfigs

Usage:
  rosa list kubeletconfigs [flags]

Aliases:
  kubeletconfigs, kubelet-configs, kubeletconfig, kubelet-config

Examples:
 # List the kubeletconfigs for cluster 'foo'
rosa list kubeletconfig --cluster foo

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for kubeletconfigs
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list log-forwarders

```
List log forwarders configured on a cluster, given a cluster ID

Usage:
  rosa list log-forwarders -c <cluster-id> [flags]

Aliases:
  log-forwarders, logforwarders, log-forwarder, logforwarder

Examples:
  # List all log forwarders on a cluster named "mycluster": rosa list log-forwarders --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for log-forwarders
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list machinepools

```
List machine pools configured on a cluster.

Usage:
  rosa list machinepools [flags]

Aliases:
  machinepools, machinepool, machine-pools, machine-pool

Examples:
  # List all machine pools on a cluster named "mycluster"
  rosa list machinepools --cluster=mycluster
  
  # List machine pools showing all information
  rosa list machinepools --cluster=mycluster --all

Flags:
      --all              Show all additional information for each machine pool (equivalent to --az-type --dedicated-host --win-li)
      --az-type          Show the availability zone type for each machine pool
  -c, --cluster string   Name or ID of the cluster.
      --dedicated-host   Show whether each machine pool is using a dedicated host
  -h, --help             help for machinepools
  -o, --output string    Output format. Allowed formats are [json yaml]
      --win-li           Show whether each machine pool is Windows LI enabled

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list ocm-roles

```
List ocm roles for the current AWS account.

Usage:
  rosa list ocm-roles [flags]

Aliases:
  ocm-roles, ocmrole, ocm-role, ocmroles, ocm-roles

Examples:
 # List all ocm roles
rosa list ocm-roles

Flags:
  -h, --help            help for ocm-roles
  -o, --output string   Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list oidc-config

```
List OIDC Configuration resources

Usage:
  rosa list oidc-config [flags]

Aliases:
  oidc-config, oidcconfig, oidcconfigs

Examples:
  # List all OIDC Configurations tied to your organization ID"
  rosa list oidc-config

Flags:
  -h, --help            help for oidc-config
  -o, --output string   Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list oidc-providers

```
List OIDC providers for the current AWS account.

Usage:
  rosa list oidc-providers [flags]

Aliases:
  oidc-providers, oidcprovider, oidc-provider, oidcproviders

Examples:
  # List all oidc providers
  rosa list oidc-providers

Flags:
  -o, --output string           Output format. Allowed formats are [json yaml]
  -c, --cluster string          Name or ID of the cluster.
      --oidc-config-id string   Filter by OIDC Config ID, returns one provider linked to the config ID.
  -h, --help                    help for oidc-providers

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list operator-roles

```
List operator roles and policies for the current AWS account.

Usage:
  rosa list operator-roles [flags]

Aliases:
  operator-roles, operatorrole, operator-role, operatorroles

Examples:
  # List all operator roles
  rosa list operator-roles

Flags:
      --version string   List only operator-roles that are associated with the given version.
      --prefix string    List only operator-roles that are associated with the given prefix. The prefix must match up to openshift|kube-system
  -i, --interactive      Enable interactive mode.
  -c, --cluster string   Name or ID of the cluster.
  -o, --output string    Output format. Allowed formats are [json yaml]
  -h, --help             help for operator-roles

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list regions

```
List regions that are available for the current AWS account.

Usage:
  rosa list regions [flags]

Aliases:
  regions, region

Examples:
  # List all available regions
  rosa list regions

Flags:
      --external-id string   A unique identifier that might be required when you assume a role in another account
  -h, --help                 help for regions
      --hosted-cp            List only regions with support for Hosted Control Planes
      --multi-az             List only regions with support for multiple availability zones
  -o, --output string        Output format. Allowed formats are [json yaml]
      --role-arn string      The Amazon Resource Name of the role that the API will assume to fetch available regions.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list tuning-configs

```
List tuning configuration resources for a cluster.

Usage:
  rosa list tuning-configs [flags]

Aliases:
  tuning-configs, tuningconfig, tuningconfigs, tuning-config

Examples:
  # List all tuning configuration for a cluster named 'mycluster'"
  rosa list tuning-configs -c mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for tuning-configs
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list upgrades

```
List available and scheduled cluster version upgrades

Usage:
  rosa list upgrades [flags]

Aliases:
  upgrades, upgrade

Flags:
  -c, --cluster string       Name or ID of the cluster.
      --machinepool string   Machine pool of the cluster to target
  -y, --yes                  Automatically answer yes to confirm operation.
  -o, --output string        Output format. Allowed formats are [json yaml]
  -h, --help                 help for upgrades

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list user-roles

```
List user roles for current AWS account

Usage:
  rosa list user-roles [flags]

Aliases:
  user-roles, userrole, user-role, userroles, user-roles

Examples:
# List all user roles
rosa list user-roles

Flags:
  -h, --help            help for user-roles
  -o, --output string   Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list users

```
List administrative cluster users.

Usage:
  rosa list users [flags]

Aliases:
  users, user

Examples:
  # List all users on a cluster named "mycluster"
  rosa list users --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for users
  -o, --output string    Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa list versions

```
List versions of OpenShift that are available for creating clusters.

NOTE: Available upgrades shown in this command are deprecated.

Usage:
  rosa list versions [flags]

Aliases:
  versions, version

Examples:
  # List all OpenShift versions
  rosa list versions

Flags:
      --channel-group string   List only versions from the specified channel group (default "stable")
  -h, --help                   help for versions
      --hosted-cp              Lists only versions that are hosted-cp enabled
  -o, --output string          Output format. Allowed formats are [json yaml]

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa login

```
Log in to your Red Hat account, saving the credentials to the configuration file or OS Keyring.
The supported mechanism is by using a token, which can be obtained at: https://console.redhat.com/openshift/token/rosa

The application looks for the token in the following order, stopping when it finds it:
	1. OS Keyring via Environment variable (OCM_KEYRING)
	2. Command-line flags
	3. Environment variable (ROSA_TOKEN)
	4. Environment variable (OCM_TOKEN)
	5. Configuration file
	6. Command-line prompt

Usage:
  rosa login [flags]

Examples:
  # Login to the OpenShift API with an existing token generated from https://console.redhat.com/openshift/token/rosa
  rosa login --token=$OFFLINE_ACCESS_TOKEN

Flags:
      --client-id string       OpenID client identifier. The default value is 'cloud-services'.
      --client-secret string   OpenID client secret.
      --govcloud               Uses the FedRAMP High OpenShift Cluster Manager API for creating clusters in AWS GovCloud regions
  -h, --help                   help for login
      --insecure               Enables insecure communication with the server. This disables verification of TLS certificates and host names.
      --region string          Use a specific AWS region, overriding the AWS_REGION environment variable.
      --scope strings          OpenID scope. If this option is used it will completely replace the default scopes. Can be repeated multiple times to specify multiple scopes. (default [openid])
  -t, --token string           Access or refresh token generated from https://console.redhat.com/openshift/token/rosa.
      --token-url string       OpenID token URL. The default value is 'https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token'.
      --use-auth-code          Login using OAuth Authorization Code. This should be used for most cases where a browser is available. See --use-device-code for remote hosts and containers.
      --use-device-code        Login using OAuth Device Code. This should only be used for remote hosts and containers where browsers are not available. See --use-auth-code for all other scenarios.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa logout

```
Log out, removing the configuration file.

Usage:
  rosa logout [flags]

Flags:
  -h, --help   help for logout

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa logs

```
Show installation or uninstallation logs for a cluster

Usage:
  rosa logs [command]

Aliases:
  logs, log

Examples:
  # Show install logs for a cluster named 'mycluster'
  rosa logs install --cluster=mycluster

  # Show uninstall logs for a cluster named 'mycluster'
  rosa logs uninstall --cluster=mycluster

Available Commands:
  install     Show cluster installation logs
  uninstall   Show cluster uninstallation logs

Flags:
  -h, --help             help for logs
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa logs [command] --help" for more information about a command.
```


### rosa logs install

```
Show cluster installation logs

Usage:
  rosa logs install [flags]

Examples:
  # Show last 100 install log lines for a cluster named "mycluster"
  rosa logs install mycluster --tail=100

  # Show install logs for a cluster using the --cluster flag
  rosa logs install --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for install
      --tail int         Number of lines to get from the end of the log. (default 2000)
  -w, --watch            After getting the logs, watch for changes.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa logs uninstall

```
Show cluster uninstallation logs

Usage:
  rosa logs uninstall [flags]

Examples:
  # Show last 100 uninstall log lines for a cluster named "mycluster"
  rosa logs uninstall mycluster --tail=100

  # Show uninstall logs for a cluster using the --cluster flag
  rosa logs uninstall --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for uninstall
      --tail int         Number of lines to get from the end of the log. (default 2000)
  -w, --watch            After getting the logs, watch for changes.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa register

```
Registers a specific resource

Usage:
  rosa register [command]

Aliases:
  register, registers

Available Commands:
  oidc-config Registers unmanaged OIDC config with Openshift Clusters Manager.

Flags:
  -h, --help             help for register
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa register [command] --help" for more information about a command.
```


### rosa register oidc-config

```
Registers unmanaged OIDC config with Openshift Clusters Manager.

Usage:
  rosa register oidc-config [flags]

Aliases:
  oidc-config, oidcconfig, oidcconfig

Examples:
  # Register OIDC config
	rosa register oidc-config

Flags:
  -h, --help                help for oidc-config
  -i, --interactive         Enable interactive mode.
      --issuer-url string   Issuer/Bucket URL.
  -m, --mode string         How to perform the operation. Valid options are:
                            auto: Resource changes will be automatic applied using the current AWS account
                            manual: Commands necessary to modify AWS resources will be output to be run manually
  -o, --output string       Output format. Allowed formats are [json yaml]
      --role-arn string     STS Role ARN with get secrets permission.
      --secret-arn string   Secrets Manager ARN with private key secret.
  -y, --yes                 Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa revoke

```
Revoke role from a specific resource

Usage:
  rosa revoke [command]

Available Commands:
  break-glass-credentials Revoke break glass credentials
  user                    Revoke role from users

Flags:
  -h, --help             help for revoke
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa revoke [command] --help" for more information about a command.
```


### rosa revoke break-glass-credentials

```
Revoke all the break glass credentials from a cluster.

Usage:
  rosa revoke break-glass-credentials [flags]

Aliases:
  break-glass-credentials, break-glass-credential, breakglasscredential, breakglasscredentials

Examples:
  # Revoke all break glass credentials
  rosa revoke break-glass-credentials --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for break-glass-credentials

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


### rosa revoke user

```
Revoke role from cluster user

Usage:
  rosa revoke user ROLE [flags]

Aliases:
  user, role

Examples:
  # Revoke cluster-admin role from a user
  rosa revoke user cluster-admins --user=myusername --cluster=mycluster

  # Revoke dedicated-admin role from a user
  rosa revoke user dedicated-admins --user=myusername --cluster=mycluster

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for user
  -u, --user string      Username to revoke the role from (required).

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
  -y, --yes              Automatically answer yes to confirm operation.
```


## rosa token

```
Uses the stored credentials to generate a token.

Usage:
  rosa token [flags]

Flags:
      --generate    Generate a new token.
      --header      Print the JSON header.
  -h, --help        help for token
      --payload     Print the JSON payload.
      --refresh     Print the refresh token instead of the access token.
      --signature   Print the signature.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa uninstall

```
Uninstalls a resource from a cluster

Usage:
  rosa uninstall [command]

Available Commands:
  addon       Uninstall add-on from cluster

Flags:
  -h, --help             help for uninstall
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa uninstall [command] --help" for more information about a command.
```


### rosa uninstall addon

```
Uninstall Red Hat managed add-on from a cluster

Usage:
  rosa uninstall addon ID [flags]

Aliases:
  addon, addons, add-on, add-ons

Examples:
  # Remove the CodeReady Workspaces add-on installation from the cluster
  rosa uninstall addon --cluster=mycluster codeready-workspaces

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for addon
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa unlink

```
UnLink a ocm/user role from stdin

Usage:
  rosa unlink [command]

Aliases:
  unlink, unlink

Available Commands:
  ocm-role    Unlink ocm role from a specific OCM organization
  user-role   Unlink user role from a specific OCM account

Flags:
  -h, --help             help for unlink
      --profile string   Use a specific AWS profile from your credential file.
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa unlink [command] --help" for more information about a command.
```


### rosa unlink ocm-role

```
Unlink ocm role from a specific OCM organization

Usage:
  rosa unlink ocm-role [flags]

Aliases:
  ocm-role, ocmrole

Examples:
 #Unlink ocm role
rosa unlink ocm-role --role-arn arn:aws:iam::123456789012:role/ManagedOpenshift-OCM-Role

Flags:
  -h, --help                     help for ocm-role
  -i, --interactive              Enable interactive mode.
      --organization-id string   OCM organization id to unlink the ocm role ARN
      --role-arn string          Role ARN to identify the ocm-role to be unlinked from the OCM organization
  -y, --yes                      Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
```


### rosa unlink user-role

```
Unlink user role from a specific OCM account

Usage:
  rosa unlink user-role [flags]

Aliases:
  user-role, userrole

Examples:
 # Unlink user role
rosa unlink user-role --role-arn arn:aws:iam::{accountid}:role/{prefix}-User-{username}-Role

Flags:
      --account-id string   OCM account id to unlink the user role ARN
  -h, --help                help for user-role
  -i, --interactive         Enable interactive mode.
      --role-arn string     Role ARN to identify the user-role to be unlinked from the OCM account
  -y, --yes                 Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
```


## rosa upgrade

```
Upgrade a resource

Usage:
  rosa upgrade [command]

Available Commands:
  account-roles  Upgrade account-wide IAM roles to the latest version.
  cluster        Upgrade cluster
  machinepool    Upgrade machinepool
  operator-roles Upgrade operator IAM roles for a cluster.
  roles          Upgrade cluster-specific IAM roles to the latest version.

Flags:
  -h, --help             help for upgrade
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa upgrade [command] --help" for more information about a command.
```


### rosa upgrade account-roles

```
Upgrade account-wide IAM roles to the latest version before upgrading your cluster.

Usage:
  rosa upgrade account-roles [flags]

Aliases:
  account-roles, account-role, accountroles, policies

Examples:
  # Upgrade account roles for ROSA STS clusters
  rosa upgrade account-roles

Flags:
  -h, --help             help for account-roles
      --hosted-cp        Enable the use of Hosted Control Planes
  -i, --interactive      Enable interactive mode.
  -m, --mode string      How to perform the operation. Valid options are:
                         auto: Resource changes will be automatic applied using the current AWS account
                         manual: Commands necessary to modify AWS resources will be output to be run manually
  -p, --prefix string    User-defined prefix for all generated AWS resources
      --version string   Version of OpenShift that will be used to setup policy tag, for example "4.11"
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa upgrade cluster

```
Upgrade cluster to a new available version. Use '--dry-run' to acknowledge any gates prior to attempting an upgrade

Usage:
  rosa upgrade cluster [flags]

Examples:
  # Interactively schedule an upgrade on the cluster named "mycluster"
  rosa upgrade cluster --cluster=mycluster --interactive

  # Schedule a cluster upgrade within the hour
  rosa upgrade cluster -c mycluster --version 4.12.20

  # Check if any gates need to be acknowledged prior to attempting an upgrading
  rosa upgrade cluster -c mycluster --version 4.12.20 --dry-run

Flags:
  -c, --cluster string                   Name or ID of the cluster.
  -m, --mode string                      How to perform the operation. Valid options are:
                                         auto: Resource changes will be automatic applied using the current AWS account
                                         manual: Commands necessary to modify AWS resources will be output to be run manually
      --version string                   Version of OpenShift that the cluster will be upgraded to
      --schedule-date string             Next date the upgrade should run at the specified UTC time. Format should be 'yyyy-mm-dd'
      --schedule-time string             Next UTC time that the upgrade should run on the specified date. Format should be 'HH:mm'
      --schedule string                  cron expression in UTC which will be the time when an upgrade to the latest release will be automatically scheduled and repeated at each occurrence. Mutually exclusive with --schedule-date and --schedule-time. This is currently supported only for Hosted Control Planes. 
      --node-drain-grace-period string   You may set a grace period for how long Pod Disruption Budget-protected workloads will be respected during upgrades.
                                         After this grace period, any workloads protected by Pod Disruption Budgets that have not been successfully drained from a node will be forcibly evicted.
                                         Valid options are ['15 minutes','30 minutes','45 minutes','1 hour','2 hours','4 hours','8 hours']
                                         This flag is not supported for Hosted Control Planes. (default "1 hour")
      --dry-run                          Simulate upgrading the cluster, or run through acknowledgements required to upgrade prior to upgrading a cluster.
  -y, --yes                              Automatically answer yes to confirm operation.
  -h, --help                             help for cluster

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
  -i, --interactive      Enable interactive mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa upgrade machinepool

```
Upgrade machinepool to a new available version. This is supported only for Hosted Control Planes.

Usage:
  rosa upgrade machinepool [flags]

Aliases:
  machinepool, machinepools, machine-pool, machine-pools

Examples:
  # Interactively schedule an upgrade on the cluster named "mycluster"" for a machinepool named "np1"
  rosa upgrade machinepool np1 --cluster=mycluster --interactive

  # Schedule a machinepool upgrade within the hour
  rosa upgrade machinepool np1 -c mycluster --version 4.12.20

Flags:
  -c, --cluster string         Name or ID of the cluster.
      --version string         Version of OpenShift that the machine pool will be upgraded to
      --schedule-date string   Next date the upgrade should run at the specified UTC time. Format should be 'yyyy-mm-dd'
      --schedule-time string   Next UTC time that the upgrade should run on the specified date. Format should be 'HH:mm'
      --schedule string        cron expression in UTC which will be the time when an upgrade to the latest release will be automatically scheduled and repeated at each occurrence. Mutually exclusive with --schedule-date and --schedule-time. 
  -y, --yes                    Automatically answer yes to confirm operation.
  -i, --interactive            Enable interactive mode.
  -h, --help                   help for machinepool

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa upgrade operator-roles

```
Upgrade cluster-specific operator IAM roles to latest version.

Usage:
  rosa upgrade operator-roles [flags]

Aliases:
  operator-roles, operator-role, operatorroles

Examples:
  # Upgrade cluster-specific operator IAM roles
  rosa upgrade operators-roles

Flags:
  -c, --cluster string   Name or ID of the cluster.
  -h, --help             help for operator-roles
  -i, --interactive      Enable interactive mode.
  -m, --mode string      How to perform the operation. Valid options are:
                         auto: Resource changes will be automatic applied using the current AWS account
                         manual: Commands necessary to modify AWS resources will be output to be run manually
      --version string   Version of OpenShift that the cluster will be upgraded to
  -y, --yes              Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


### rosa upgrade roles

```
Upgrade cluster-specific IAM roles to the latest version before upgrading your cluster.

Usage:
  rosa upgrade roles [flags]

Examples:
  # Upgrade cluster roles for ROSA STS clusters
		rosa upgrade roles -c <cluster_key>

Flags:
  -c, --cluster string           Name or ID of the cluster.
      --cluster-version string   Version of OpenShift that the cluster will be upgraded to
  -h, --help                     help for roles
  -i, --interactive              Enable interactive mode.
  -m, --mode string              How to perform the operation. Valid options are:
                                 auto: Resource changes will be automatic applied using the current AWS account
                                 manual: Commands necessary to modify AWS resources will be output to be run manually
  -y, --yes                      Automatically answer yes to confirm operation.

Global Flags:
      --color string     Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug            Enable debug mode.
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable. (DEPRECATED: Region flag will be removed from this command in future versions)
```


## rosa verify

```
Verify resources are configured correctly for cluster install

Usage:
  rosa verify [command]

Available Commands:
  network          Verify VPC subnets are configured correctly
  openshift-client Verify OpenShift client tools
  permissions      Verify AWS permissions are ok for non-STS cluster install
  quota            Verify AWS quota is ok for cluster install
  rosa-client      Verify ROSA client tools

Flags:
  -h, --help   help for verify

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.

Use "rosa verify [command] --help" for more information about a command.
```


### rosa verify network

```
Verify that the VPC subnets are configured correctly.

Usage:
  rosa verify network [flags]

Examples:
  # Verify two subnets
	rosa verify network --subnet-ids subnet-03046a9b92b5014fb,subnet-03046a9c92b5014fb

Flags:
  -c, --cluster string       Name or ID of the cluster.
  -h, --help                 help for network
      --hosted-cp            Run network verifier with hosted control plane platform configuration
  -o, --output string        Output format. Allowed formats are [json yaml]
      --profile string       Use a specific AWS profile from your credential file.
      --region string        Use a specific AWS region, overriding the AWS_REGION environment variable.
      --role-arn string      STS Role ARN with get secrets permission.
  -s, --status-only          Check status of previously submitted subnets.
      --subnet-ids strings   The Subnet IDs to verify. Format should be a comma-separated list.
      --tags strings         Supply custom tags to the network verifier. Tags will default to cluster tags if a cluster is supplied. Tags are comma separated, for example: 'key value, foo bar'
  -w, --watch                Watch network verification progress.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa verify openshift-client

```
Verify that the OpenShift client tools is installed and compatible.

Usage:
  rosa verify openshift-client [flags]

Aliases:
  openshift-client, oc, openshift

Examples:
  # Verify oc client tools
  rosa verify oc

Flags:
  -h, --help   help for openshift-client

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa verify permissions

```
Verify AWS permissions needed to create a non-STS cluster are configured as expected

Usage:
  rosa verify permissions [flags]

Aliases:
  permissions, scp

Examples:
  # Verify AWS permissions are configured correctly
  rosa verify permissions

  # Verify AWS permissions in a different region
  rosa verify permissions --region=us-west-2

Flags:
  -h, --help             help for permissions
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa verify quota

```
Verify AWS quota needed to create a cluster is configured as expected

Usage:
  rosa verify quota [flags]

Examples:
  # Verify AWS quotas are configured correctly
  rosa verify quota

  # Verify AWS quotas in a different region
  rosa verify quota --region=us-west-2

Flags:
  -h, --help             help for quota
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


### rosa verify rosa-client

```
Verify that the ROSA client tools is installed and compatible.

Usage:
  rosa verify rosa-client [flags]

Aliases:
  rosa-client, rosa

Examples:
  # Verify rosa client tools
  rosa verify rosa

Flags:
  -h, --help   help for rosa-client

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa version

```
Prints the version number of the tool.

Usage:
  rosa version [flags]

Flags:
      --client    Client version only (no remote version check)
  -v, --verbose   Display verbose version information, including download locations
  -h, --help      help for version

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


## rosa whoami

```
Displays information about your AWS and Red Hat accounts

Usage:
  rosa whoami [flags]

Examples:
  # Displays user information
  rosa whoami

Flags:
  -h, --help             help for whoami
  -o, --output string    Output format. Allowed formats are [json yaml]
      --profile string   Use a specific AWS profile from your credential file.
      --region string    Use a specific AWS region, overriding the AWS_REGION environment variable.

Global Flags:
      --color string   Surround certain characters with escape sequences to display them in color on the terminal. Allowed options are [auto never always] (default "auto")
      --debug          Enable debug mode.
```


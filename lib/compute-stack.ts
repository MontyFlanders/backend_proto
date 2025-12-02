import * as cdk from 'aws-cdk-lib';
import { Stack, StackProps, CfnOutput } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecs_patterns from 'aws-cdk-lib/aws-ecs-patterns';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secrets from 'aws-cdk-lib/aws-secretsmanager';
import * as servicediscovery from 'aws-cdk-lib/aws-servicediscovery';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as route53_targets from 'aws-cdk-lib/aws-route53-targets';
import * as efs from 'aws-cdk-lib/aws-efs';

export interface ComputeStackProps extends StackProps {
  vpc: ec2.IVpc;
  bucket: s3.IBucket;
  db: rds.IDatabaseInstance;
  dbSecret: secrets.ISecret;
  keycloakAdmin: secrets.ISecret;
  neoFs: efs.IFileSystem; // keep
}

export class ComputeStack extends Stack {
  constructor(scope: Construct, id: string, props: ComputeStackProps) {
    super(scope, id, props);

    // ====== CONFIG YOU CAN TWEAK ======
    const allowedIp = '155.98.131.4/32';

    // Domain settings (pass via env on deploy)
    const zoneName = process.env.ZONE_NAME;   // e.g. antiquityatlas.com
    const hostName = process.env.HOSTNAME;    // e.g. auth
    if (!zoneName || !hostName) {
      throw new Error('Please set ZONE_NAME and HOSTNAME env vars (e.g. ZONE_NAME=antiquityatlas.com HOSTNAME=auth)');
    }
    const fqdn = `${hostName}.${zoneName}`;

    const appDbName = 'appdb';
    const keycloakDbName = 'keycloak';
    const paused = this.node.tryGetContext('paused') === 'true';

    const cluster = new ecs.Cluster(this, 'Cluster', { vpc: props.vpc });
    const namespace = new servicediscovery.PrivateDnsNamespace(this, 'NS', {
      name: 'antiquity.internal',
      vpc: props.vpc,
    });

    // ====== Route53 Hosted Zone and ACM cert for FQDN ======
    const zone = route53.HostedZone.fromLookup(this, 'Zone', { domainName: zoneName });
    const cert = new acm.DnsValidatedCertificate(this, 'KeycloakCert', {
      domainName: fqdn,
      hostedZone: zone,
      region: this.region,
    });

    const apiFqdn = `api.${zoneName}`;
    const apiCert = new acm.Certificate(this, 'ApiCert', {
      domainName: apiFqdn,
      validation: acm.CertificateValidation.fromDns(zone),
    });

    // -------------------------
    // Keycloak
    // -------------------------
    const kcTaskRole = new iam.Role(this, 'KcTaskRole', { assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com') });
    props.dbSecret.grantRead(kcTaskRole);
    props.keycloakAdmin.grantRead(kcTaskRole);

    const kcTaskDef = new ecs.FargateTaskDefinition(this, 'KcTaskDef', {
      cpu: 1024, memoryLimitMiB: 2048, taskRole: kcTaskRole,
    });

    const kcContainer = kcTaskDef.addContainer('keycloak', {
      image: ecs.ContainerImage.fromRegistry('quay.io/keycloak/keycloak:23.0.6'),
      command: ['start'],
      portMappings: [{ containerPort: 8080 }],
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'keycloak' }),
      environment: {
        KC_DB: 'postgres',
        KC_DB_URL: `jdbc:postgresql://${props.db.instanceEndpoint.hostname}:5432/${keycloakDbName}`,
        KC_DB_USERNAME: 'postgres',
        KC_HTTP_ENABLED: 'true',
        KC_HEALTH_ENABLED: 'true',
        KC_PROXY: 'edge',
        KC_PROXY_HEADERS: 'xforwarded',
        KC_HOSTNAME_URL: '',
        KC_HOSTNAME_STRICT: 'false',
      },
      secrets: {
        KC_DB_PASSWORD: ecs.Secret.fromSecretsManager(props.dbSecret, 'password'),
        KEYCLOAK_ADMIN: ecs.Secret.fromSecretsManager(props.keycloakAdmin, 'username'),
        KEYCLOAK_ADMIN_PASSWORD: ecs.Secret.fromSecretsManager(props.keycloakAdmin, 'password'),
      },
    });

    const kcSvc = new ecs_patterns.ApplicationLoadBalancedFargateService(this, 'KeycloakSvc', {
      cluster,
      publicLoadBalancer: true,
      certificate: cert,
      redirectHTTP: true,
      listenerPort: 443,
      openListener: false,
      desiredCount: paused ? 0 : 1,
      assignPublicIp: false,
      taskDefinition: kcTaskDef,
      taskSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      healthCheckGracePeriod: cdk.Duration.minutes(15),
    });

    kcContainer.addEnvironment('KC_HOSTNAME_URL', `https://${fqdn}`);

    kcSvc.targetGroup.configureHealthCheck({
      path: '/',
      healthyHttpCodes: '200-399',
      port: 'traffic-port',
    });

    const kcAlbSg = kcSvc.loadBalancer.connections.securityGroups[0];
    kcAlbSg.addIngressRule(ec2.Peer.ipv4(allowedIp), ec2.Port.tcp(443), 'Allow HTTPS from my IP');
    kcAlbSg.addIngressRule(ec2.Peer.ipv4(allowedIp), ec2.Port.tcp(80), 'Allow HTTP redirect from my IP');

    kcSvc.service.connections.allowFrom(kcSvc.loadBalancer, ec2.Port.tcp(8080));

    const cfnKcSvc = kcSvc.service.node.defaultChild as ecs.CfnService;
    cfnKcSvc.deploymentConfiguration = {
      deploymentCircuitBreaker: { enable: true, rollback: true },
    };

    new route53.ARecord(this, 'KeycloakAlias', {
      zone,
      recordName: hostName,
      target: route53.RecordTarget.fromAlias(new route53_targets.LoadBalancerTarget(kcSvc.loadBalancer)),
      ttl: cdk.Duration.minutes(1),
    });

    kcSvc.service.enableCloudMap({ name: 'keycloak', cloudMapNamespace: namespace });

    // -------------------------
    // API (FastAPI/GraphQL)
    // -------------------------
    const openAiSecret = secrets.Secret.fromSecretNameV2(
      this,
      'OpenAISecret',
      'antiquity-atlas/openai',
    );
    

    const apiTaskRole = new iam.Role(this, 'ApiTaskRole', { assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com') });
    props.bucket.grantReadWrite(apiTaskRole);
    props.dbSecret.grantRead(apiTaskRole);
    openAiSecret.grantRead(apiTaskRole);

    const apiTaskDef = new ecs.FargateTaskDefinition(this, 'ApiTaskDef', {
      cpu: 512,
      memoryLimitMiB: 1024,
      taskRole: apiTaskRole,
    });

    const apiContainer = apiTaskDef.addContainer('api', {
      image: ecs.ContainerImage.fromAsset('.', {
        file: 'Dockerfile',
        // platform: ecr_assets.Platform.LINUX_AMD64,
      }),
      portMappings: [{ containerPort: 8000 }],
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'api' }),
      environment: {
        // Postgres (RDS)
        DB_HOST: props.db.instanceEndpoint.hostname,
        DB_PORT: '5432',
        DB_USER: 'postgres',
        DB_NAME: appDbName,

        // S3
        S3_BUCKET: props.bucket.bucketName,
        AWS_REGION: this.region,

        // OIDC / Keycloak issuer (HTTPS through ALB)
        OIDC_ISSUER: `https://${fqdn}/realms/dev`,
      },
      secrets: {
        DB_PASSWORD: ecs.Secret.fromSecretsManager(props.dbSecret, 'password'),
        OPENAI_API_KEY: ecs.Secret.fromSecretsManager(openAiSecret, 'OPENAI_API_KEY'),
      },
    });


    const apiSvc = new ecs_patterns.ApplicationLoadBalancedFargateService(this, 'ApiSvc', {
      cluster,
      publicLoadBalancer: true,
      certificate: apiCert,
      redirectHTTP: true,
      listenerPort: 443,
      openListener: false,
      desiredCount: paused ? 0 : 1,
      assignPublicIp: false,
      taskDefinition: apiTaskDef,
      taskSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });

    new route53.ARecord(this, 'ApiAlias', {
      zone,
      recordName: 'api',
      target: route53.RecordTarget.fromAlias(new route53_targets.LoadBalancerTarget(apiSvc.loadBalancer)),
      ttl: cdk.Duration.minutes(1),
    });
    apiSvc.targetGroup.configureHealthCheck({ path: '/healthz', healthyHttpCodes: '200-399' });

    apiSvc.service.enableCloudMap({ name: 'api', cloudMapNamespace: namespace });
    const apiAlbSg = apiSvc.loadBalancer.connections.securityGroups[0];
    apiAlbSg.addIngressRule(ec2.Peer.ipv4(allowedIp), ec2.Port.tcp(443), 'Allow HTTPS');
    apiAlbSg.addIngressRule(ec2.Peer.ipv4(allowedIp), ec2.Port.tcp(80), 'Allow HTTP redirect');

    // -------------------------
    // Neo4j on Fargate (with EFS)
    // -------------------------
    const neoTaskRole = new iam.Role(this, 'NeoTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    const neo4jPassword = process.env.NEO4J_PASSWORD ?? 'change-me-dev-1234';

    // Secret value is JSON: {"NEO4J_AUTH": "neo4j/<pwd>"}
    const neoAuth = new secrets.Secret(this, 'Neo4jAuth', {
      secretObjectValue: {
        NEO4J_AUTH: cdk.SecretValue.unsafePlainText(`neo4j/${neo4jPassword}`),
        password: cdk.SecretValue.unsafePlainText(neo4jPassword),
      },
    });

    const neoAp = new efs.AccessPoint(this, 'NeoAccessPoint', {
      fileSystem: props.neoFs,
      path: '/neo4j',
      posixUser: { uid: '7474', gid: '7474' },
      createAcl: { ownerUid: '7474', ownerGid: '7474', permissions: '750' },
    });

    const neoSg = new ec2.SecurityGroup(this, 'NeoSg', {
      vpc: props.vpc,
      allowAllOutbound: true,
    });

    const neoTaskDef = new ecs.FargateTaskDefinition(this, 'NeoTaskDef', {
      cpu: 1024,
      memoryLimitMiB: 2048,
      taskRole: neoTaskRole,
    });

    const neoContainer = neoTaskDef.addContainer('neo4j', {
      image: ecs.ContainerImage.fromRegistry('public.ecr.aws/docker/library/neo4j:5.15'),
      portMappings: [
        { containerPort: 7687 }, // Bolt
        { containerPort: 7474 }, // HTTP
      ],
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'neo4j' }),

      // ✅ Only server settings Neo understands
      environment: {
        // listen on all interfaces
        NEO4J_server_default__listen__address: '0.0.0.0',
        NEO4J_server_bolt_listen__address: ':7687',
        NEO4J_server_http_enabled: 'true',
        NEO4J_server_http_listen__address: ':7474',
        NEO4J_server_https_enabled: 'false',

        // (optional) be lenient while iterating
        NEO4J_server_config_strict__validation_enabled: 'false',

        // ✅ v5 memory keys (avoid the deprecation warnings)
        NEO4J_server_memory_heap_initial__size: '768m',
        NEO4J_server_memory_heap_max__size: '768m',
      },

      secrets: {
        // ✅ Only this belongs on the Neo container
        NEO4J_AUTH: ecs.Secret.fromSecretsManager(neoAuth, 'NEO4J_AUTH'),
      },

      // ✅ Simple TCP healthcheck; no curl/wget dependency
      healthCheck: {
        command: ['CMD-SHELL', 'bash -lc "exec 3<>/dev/tcp/127.0.0.1/7474" || exit 1'],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 10,
        startPeriod: cdk.Duration.seconds(300),
      },
    });


    neoTaskDef.addVolume({
      name: 'neo',
      efsVolumeConfiguration: {
        fileSystemId: props.neoFs.fileSystemId,
        transitEncryption: 'ENABLED',
        authorizationConfig: { accessPointId: neoAp.accessPointId },
      },
    });

    neoContainer.addMountPoints({
      containerPath: '/data',
      readOnly: false,
      sourceVolume: 'neo',
    });

    const neoSvc = new ecs.FargateService(this, 'NeoSvc', {
      cluster,
      taskDefinition: neoTaskDef,
      desiredCount: 1,
      assignPublicIp: false,
      minHealthyPercent: 0,   // stop old before start new
      maxHealthyPercent: 100,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      cloudMapOptions: { name: 'neo4j', cloudMapNamespace: namespace },
      securityGroups: [neoSg],
    });


    neoAuth.grantRead(neoTaskDef.obtainExecutionRole());   // allow ECS to fetch secret value
    // props.neoFs.connections.allowDefaultPortFrom(neoSg);   // allow NFS 2049 from task ENIs
    neoSvc.node.addDependency(neoAp);                      // ensure AP exists before service
    // Allow API → Neo4j (Bolt + optional Browser)
    neoSg.addIngressRule(
      apiSvc.service.connections.securityGroups[0],
      ec2.Port.tcp(7687),
      'API to Neo4j (Bolt)'
    );
    neoSg.addIngressRule(
      apiSvc.service.connections.securityGroups[0],
      ec2.Port.tcp(7474),
      'API to Neo4j HTTP'
    );

    apiContainer.addEnvironment('NEO4J_URI', 'bolt://neo4j.antiquity.internal:7687'); // your CloudMap name
    apiContainer.addEnvironment('NEO4J_USER', 'neo4j');
    apiContainer.addSecret('NEO4J_PASSWORD', ecs.Secret.fromSecretsManager(neoAuth, 'password'));
    // EFS NFS from Neo4j service
    // EFS NFS from Neo4j service (L2, avoids any ImportValue/exports)
    new ec2.CfnSecurityGroupIngress(this, 'NeoToEfsNfs', {
      groupId: props.neoFs.connections.securityGroups[0].securityGroupId, // ✅ EFS SG
      sourceSecurityGroupId: neoSg.securityGroupId,                       // ✅ Neo SG
      ipProtocol: 'tcp',
      fromPort: 2049,
      toPort: 2049,
      description: 'Neo4j to EFS (NFS)',
    });
    // Service-to-service allows
    kcSvc.service.connections.allowFrom(apiSvc.service, ec2.Port.tcp(8080));

    new CfnOutput(this, 'KeycloakUrl', { value: `https://${fqdn}` });
    new CfnOutput(this, 'ApiAlbDns', { value: apiSvc.loadBalancer.loadBalancerDnsName });
    new CfnOutput(this, 'KeycloakAlbDns', { value: kcSvc.loadBalancer.loadBalancerDnsName });
  }
}

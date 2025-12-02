import * as cdk from 'aws-cdk-lib';
import { Stack, StackProps, RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secrets from 'aws-cdk-lib/aws-secretsmanager';
import * as efs from 'aws-cdk-lib/aws-efs';

export class DataStack extends Stack {
  public readonly vpc: ec2.Vpc;
  public readonly bucket: s3.Bucket;
  public readonly db: rds.DatabaseInstance;
  public readonly dbSecret: secrets.Secret;
  public readonly keycloakAdmin: secrets.Secret;
  public readonly neoFs: efs.FileSystem;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    this.vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
    });

    this.bucket = new s3.Bucket(this, 'Assets', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    this.dbSecret = new secrets.Secret(this, 'DbSecret', {
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: 'postgres' }),
        generateStringKey: 'password',
        excludePunctuation: true,
      },
    });

    this.keycloakAdmin = new secrets.Secret(this, 'KeycloakAdmin', {
      secretObjectValue: {
        username: cdk.SecretValue.unsafePlainText('admin'),
        password: this.dbSecret.secretValueFromJson('password'),
      },
    });

    // Legacy EFS for Neo4j
    this.neoFs = new efs.FileSystem(this, 'NeoFs', {
      vpc: this.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    this.neoFs.connections.allowFrom(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
      ec2.Port.tcp(2049),
      'VPC CIDR to EFS',
    );




    // RDS Postgres
    const rdsSg = new ec2.SecurityGroup(this, 'RdsSg', {
      vpc: this.vpc,
      allowAllOutbound: true,
    });
    rdsSg.addIngressRule(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
      ec2.Port.tcp(5432),
      'VPC CIDR to Postgres',
    );

    this.db = new rds.DatabaseInstance(this, 'Postgres', {
      vpc: this.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      credentials: rds.Credentials.fromSecret(this.dbSecret),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
      allocatedStorage: 20,
      securityGroups: [rdsSg],
      deletionProtection: false,
      removalPolicy: RemovalPolicy.DESTROY,
      databaseName: 'appdb',
    });
    
    // ---- Legacy Neptune export shims: pin to EXACT current values so CFN sees no change ----
    new cdk.CfnOutput(this, 'Compat_NeptuneWriterEndpoint', {
      value: 'neptunedbcluster-r3x0swvuc6oc.cluster-czmewq2uatq7.us-west-2.neptune.amazonaws.com:8182',
      exportName: 'NeptuneWriterEndpoint',
    });

    new cdk.CfnOutput(this, 'Compat_NeptuneReaderEndpoint', {
      value: 'neptunedbcluster-r3x0swvuc6oc.cluster-ro-czmewq2uatq7.us-west-2.neptune.amazonaws.com:8182',
      exportName: 'NeptuneReaderEndpoint',
    });

    new cdk.CfnOutput(this, 'Compat_NeptuneClusterResourceId', {
      value: 'cluster-MQ42OGNUJX5T4UVTKQ72TUTKHI',
      exportName: 'NeptuneClusterResourceId',
    });

    // Keep the *exact* old Neptune SG export value too so CFN doesn't try to delete it
    new cdk.CfnOutput(this, 'Compat_NeptuneSgGroupId', {
      value: 'sg-032c0ba70cc471884',
      exportName: 'DataStack:ExportsOutputFnGetAttNeptuneSg69803EEEGroupIdEF0D9D08',
    });
    // No manual CfnOutput for NeoFs — CDK will auto-export the values used by ComputeStack.

    // (Optional) seed role
    const seedRole = new iam.Role(this, 'SeedTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    this.bucket.grantReadWrite(seedRole);
    this.dbSecret.grantRead(seedRole);
  }
}

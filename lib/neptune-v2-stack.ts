// lib/neptune-v2-stack.ts
import * as cdk from 'aws-cdk-lib';
import { Stack, StackProps, CfnOutput } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
// Use the same alpha module your working DataStack uses
import * as neptune from '@aws-cdk/aws-neptune-alpha';

export interface NeptuneV2StackProps extends StackProps {
  vpc: ec2.IVpc;
}

export class NeptuneV2Stack extends Stack {
  public readonly neptuneSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NeptuneV2StackProps) {
    super(scope, id, props);

    // SG for Neptune V2 (ComputeStack will allow API SG -> 8182 to this SG)
    this.neptuneSg = new ec2.SecurityGroup(this, 'NeptuneSgV2', {
      vpc: props.vpc,
      allowAllOutbound: true,
      description: 'Security group for Neptune V2 cluster',
    });

    // Subnet group in private subnets
    const subnetGroup = new neptune.SubnetGroup(this, 'NeptuneSubnetGroupV2', {
      vpc: props.vpc,
      description: 'Subnets for Neptune V2',
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Serverless Neptune cluster (V2)
    const clusterV2 = new neptune.DatabaseCluster(this, 'NeptuneClusterV2', {
      vpc: props.vpc,
      securityGroups: [this.neptuneSg],
      subnetGroup,
      instanceType: neptune.InstanceType.SERVERLESS,
      serverlessScalingConfiguration: { minCapacity: 1, maxCapacity: 5 },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Exports with V2 names
    new CfnOutput(this, 'NeptuneWriterEndpointV2', {
      value: clusterV2.clusterEndpoint.socketAddress, // host:port
      exportName: 'NeptuneWriterEndpointV2',
    });
    new CfnOutput(this, 'NeptuneReaderEndpointV2', {
      value: clusterV2.clusterReadEndpoint.socketAddress,
      exportName: 'NeptuneReaderEndpointV2',
    });
    new CfnOutput(this, 'NeptuneClusterResourceIdV2', {
      value: clusterV2.clusterResourceIdentifier,
      exportName: 'NeptuneClusterResourceIdV2',
    });
  }
}

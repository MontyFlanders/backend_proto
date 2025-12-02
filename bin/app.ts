#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { DataStack } from '../lib/data-stack';
import { ComputeStack } from '../lib/compute-stack';

const app = new cdk.App();
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-west-2',
};

const data = new DataStack(app, 'DataStack', { env });



new ComputeStack(app, 'ComputeStack', {
  env,
  vpc: data.vpc,
  bucket: data.bucket,
  db: data.db,
  dbSecret: data.dbSecret,
  keycloakAdmin: data.keycloakAdmin,
  neoFs: data.neoFs,
});

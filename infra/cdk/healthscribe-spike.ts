import {
  CfnOutput,
  RemovalPolicy,
  Stack,
  StackProps,
  Validations,
} from "aws-cdk-lib";
import {
  Policy,
  PolicyStatement,
  Role,
  ServicePrincipal,
} from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import {
  BlockPublicAccess,
  Bucket,
  BucketEncryption,
} from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

export class HealthScribeSpike extends Stack {
  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);
    const key = new Key(this, "SpikeKey", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const bucket = new Bucket(this, "SpikeBucket", {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.KMS,
      encryptionKey: key,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const role = new Role(this, "ScribeRole", {
      assumedBy: new ServicePrincipal("transcribe.amazonaws.com", {
        conditions: { StringEquals: { "aws:SourceAccount": this.account } },
      }),
    });
    const policy = new Policy(this, "ScribeDataAccess", {
      roles: [role],
      statements: [
        new PolicyStatement({
          actions: ["s3:GetBucketLocation", "s3:ListBucket"],
          resources: [bucket.bucketArn],
        }),
        new PolicyStatement({
          actions: ["s3:GetObject", "s3:PutObject"],
          resources: [bucket.arnForObjects("*")],
        }),
        new PolicyStatement({
          actions: [
            "kms:Decrypt",
            "kms:Encrypt",
            "kms:GenerateDataKey",
            "kms:DescribeKey",
          ],
          resources: [key.keyArn],
        }),
      ],
    });
    Validations.of(policy).acknowledge({
      id: "AwsSolutions::AwsSolutions-IAM5[Resource::<SpikeBucketA0004326.Arn>/*]",
      reason:
        "HealthScribe chooses output object keys. Access is scoped to this isolated synthetic-data spike bucket.",
    });
    Validations.of(bucket).acknowledge({
      id: "AwsSolutions::AwsSolutions-S1",
      reason:
        "The dedicated synthetic-only spike bucket is emptied and destroyed after the run.",
    });
    new CfnOutput(this, "Bucket", { value: bucket.bucketName });
    new CfnOutput(this, "Role", { value: role.roleArn });
    new CfnOutput(this, "Key", { value: key.keyArn });
  }
}

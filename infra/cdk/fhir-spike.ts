import {
  CfnOutput,
  RemovalPolicy,
  Stack,
  StackProps,
  Validations,
} from "aws-cdk-lib";
import { CfnFHIRDatastore } from "aws-cdk-lib/aws-healthlake";
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

export class FhirSpike extends Stack {
  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);
    const store = new CfnFHIRDatastore(this, "Store", {
      datastoreName: "verimed-phase0-fhir-spike",
      datastoreTypeVersion: "R4",
      identityProviderConfiguration: { authorizationStrategy: "AWS_AUTH" },
    });
    const key = new Key(this, "TransferKey", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const bucket = new Bucket(this, "TransferBucket", {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.KMS,
      encryptionKey: key,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const role = new Role(this, "ImportRole", {
      assumedBy: new ServicePrincipal("healthlake.amazonaws.com", {
        conditions: { StringEquals: { "aws:SourceAccount": this.account } },
      }),
    });
    const dataAccess = new Policy(this, "DataAccess", {
      roles: [role],
      statements: [
        new PolicyStatement({
          actions: ["s3:GetBucketLocation", "s3:ListBucket"],
          resources: [bucket.bucketArn],
        }),
        new PolicyStatement({
          actions: ["s3:GetObject", "s3:PutObject"],
          resources: [bucket.arnForObjects("verimed-s4-*")],
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
    const bucketResource = bucket.node.defaultChild as Construct;
    const bucketId = this.getLogicalId(
      bucketResource as import("aws-cdk-lib").CfnElement,
    );
    Validations.of(dataAccess).acknowledge({
      id: `AwsSolutions::AwsSolutions-IAM5[Resource::<${bucketId}.Arn>/verimed-s4-*]`,
      reason:
        "Each benchmark uses a unique job prefix in a dedicated synthetic-only bucket.",
    });
    Validations.of(bucket).acknowledge({
      id: "AwsSolutions::AwsSolutions-S1",
      reason:
        "A temporary synthetic-only benchmark bucket is deleted after the import.",
    });
    new CfnOutput(this, "Datastore", { value: store.attrDatastoreId });
    new CfnOutput(this, "Bucket", { value: bucket.bucketName });
    new CfnOutput(this, "Role", { value: role.roleArn });
    new CfnOutput(this, "Key", { value: key.keyArn });
  }
}

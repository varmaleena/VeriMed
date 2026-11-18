import {
  CfnOutput,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
  Validations,
} from "aws-cdk-lib";
import { Key, KeySpec, KeyUsage } from "aws-cdk-lib/aws-kms";
import {
  Bucket,
  BucketEncryption,
  BlockPublicAccess,
  CfnBucket,
  ObjectOwnership,
} from "aws-cdk-lib/aws-s3";
import { AnyPrincipal, PolicyStatement, Effect } from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

interface LedgerProps extends StackProps {
  stage: string;
  tenant: string;
}

export class CellLedger extends Stack {
  constructor(scope: Construct, id: string, props: LedgerProps) {
    super(scope, id, props);
    this.node.setContext(
      "@aws-cdk/aws-s3:serverAccessLogsUseBucketPolicy",
      true,
    );
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", props.tenant);
    Tags.of(this).add("Env", props.stage);
    const signingKey = new Key(this, "SigningKey", {
      description: "ChartVigil tenant audit ledger signatures",
      keySpec: KeySpec.ECC_NIST_P256,
      keyUsage: KeyUsage.SIGN_VERIFY,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    // AWS KMS automatic rotation supports symmetric encryption keys only.
    // Rotate by provisioning a new key, retaining old ARNs for historical verification.
    Validations.of(signingKey).acknowledge({
      id: "AwsSolutions::AwsSolutions-KMS4",
      reason:
        "Asymmetric signing keys do not support automatic rotation; retain historical keys and rotate through new versioned keys.",
    });
    new CfnOutput(this, "SigningKeyArn", { value: signingKey.keyArn });
    const anchorKey = new Key(this, "AnchorKey", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
      description: "ChartVigil retained ledger anchor encryption",
    });
    const accessLogs = new Bucket(this, "AnchorAccessLogs", {
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    Validations.of(accessLogs).acknowledge({
      id: "AwsSolutions::AwsSolutions-S1",
      reason:
        "This is the destination for anchor bucket access logs; logging it to itself would recurse.",
    });
    const anchors = new Bucket(this, "Anchors", {
      encryption: BucketEncryption.KMS,
      encryptionKey: anchorKey,
      bucketKeyEnabled: true,
      versioned: true,
      objectLockEnabled: true,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
      serverAccessLogsBucket: accessLogs,
      serverAccessLogsPrefix: "anchors/",
    });
    const cfnAnchors = anchors.node.defaultChild as CfnBucket;
    cfnAnchors.objectLockConfiguration = {
      objectLockEnabled: "Enabled",
      rule: { defaultRetention: { mode: "COMPLIANCE", years: 7 } },
    };
    anchors.addToResourcePolicy(
      new PolicyStatement({
        effect: Effect.DENY,
        principals: [new AnyPrincipal()],
        actions: ["s3:DeleteObject"],
        resources: [anchors.arnForObjects("*")],
      }),
    );
    anchors.addToResourcePolicy(
      new PolicyStatement({
        effect: Effect.DENY,
        principals: [new AnyPrincipal()],
        actions: ["s3:PutObject"],
        resources: [anchors.arnForObjects("*")],
        conditions: { Null: { "s3:if-none-match": "true" } },
      }),
    );
    new CfnOutput(this, "AnchorBucketName", { value: anchors.bucketName });
    new CfnOutput(this, "AnchorEncryptionKeyArn", { value: anchorKey.keyArn });
  }
}

import { CfnOutput, Stack, StackProps, Tags, RemovalPolicy } from "aws-cdk-lib";
import { CfnFHIRDatastore } from "aws-cdk-lib/aws-healthlake";
import { PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import { CfnSchedule } from "aws-cdk-lib/aws-scheduler";
import { Construct } from "constructs";

interface FhirDemoProps extends StackProps {
  expiresAt: string;
}

export class CellFhirDemo extends Stack {
  constructor(scope: Construct, id: string, props: FhirDemoProps) {
    super(scope, id, props);
    const expiry = new Date(props.expiresAt);
    if (!Number.isFinite(expiry.getTime()))
      throw new Error("A valid UTC demo expiry is required");
    Tags.of(this).add("Project", "verimed");
    Tags.of(this).add("Tenant", "a");
    Tags.of(this).add("Env", "dev");
    const key = new Key(this, "FhirKey", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const store = new CfnFHIRDatastore(this, "Fhir", {
      datastoreName: "chartvigil-synthetic-test-window",
      datastoreTypeVersion: "R4",
      preloadDataConfig: { preloadDataType: "SYNTHEA" },
      identityProviderConfiguration: { authorizationStrategy: "AWS_AUTH" },
      nlpConfiguration: { status: "DISABLED" },
      sseConfiguration: {
        kmsEncryptionConfig: {
          cmkType: "CUSTOMER_MANAGED_KMS_KEY",
          kmsKeyId: key.keyArn,
        },
      },
    });
    const teardown = new Role(this, "TeardownRole", {
      assumedBy: new ServicePrincipal("scheduler.amazonaws.com", {
        conditions: { StringEquals: { "aws:SourceAccount": this.account } },
      }),
    });
    teardown.addToPolicy(
      new PolicyStatement({
        actions: ["cloudformation:DeleteStack"],
        resources: [this.stackId],
      }),
    );
    new CfnSchedule(this, "Teardown", {
      name: "chartvigil-synthetic-window-teardown",
      description:
        "Delete only the two-day synthetic FHIR demo stack after its approved test window",
      scheduleExpression: `at(${expiry.toISOString().slice(0, 19)})`,
      scheduleExpressionTimezone: "UTC",
      flexibleTimeWindow: { mode: "OFF" },
      target: {
        arn: "arn:aws:scheduler:::aws-sdk:cloudformation:deleteStack",
        roleArn: teardown.roleArn,
        input: JSON.stringify({ StackName: this.stackId }),
        retryPolicy: {
          maximumEventAgeInSeconds: 3600,
          maximumRetryAttempts: 5,
        },
      },
    });
    new CfnOutput(this, "FhirEndpoint", { value: store.attrDatastoreEndpoint });
    new CfnOutput(this, "FhirArn", { value: store.attrDatastoreArn });
    new CfnOutput(this, "ExpiresAt", { value: expiry.toISOString() });
  }
}

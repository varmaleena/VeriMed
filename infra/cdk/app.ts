import { App, Validations } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { CellIdentity } from "./cell-identity";
import { CellWorklist } from "./cell-worklist";
import { CellFhirDemo } from "./cell-fhir-demo";
import { CellFhirImport } from "./cell-fhir-import";
import { CellLedger } from "./cell-ledger";
import { HubCKS } from "./hub-cks";
import { CksCaller } from "./cks-ingress";
import { readFileSync } from "node:fs";
import { AgentCoreSpike } from "./agentcore-spike";
import { FhirSpike } from "./fhir-spike";
import { HealthScribeSpike } from "./healthscribe-spike";
import { LiteLlmSpike } from "./litellm-spike";
import { CellFoundation, HubFoundation } from "./foundation";

const app = new App();
const stage: string = app.node.tryGetContext("env") ?? "dev";
const tenant: string = app.node.tryGetContext("cell") ?? "a";
const region = process.env.AWS_REGION ?? "us-east-1";
new HubFoundation(app, "HubFoundation", {
  stage,
  tenant: "hub",
  env: { region, account: process.env.VERIMED_HUB_ACCOUNT },
});
new CellFoundation(app, "CellFoundation", {
  stage,
  tenant,
  env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
});
Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
if (app.node.tryGetContext("cellLedger") === "true") {
  const workerEnabled = app.node.tryGetContext("cellLedgerWorker") === "true";
  const workerConfig = workerEnabled
    ? {
        bundle: process.env.VERIMED_API_BUNDLE!,
        tenantId: process.env.VERIMED_TENANT_ID!,
        clusterArn: process.env.DATABASE_CLUSTER_ARN!,
        readerSecretArn: process.env.DATABASE_RUNTIME_SECRET_ARN!,
        databaseKeyArn: process.env.DATABASE_KEY_ARN!,
      }
    : undefined;
  if (workerConfig && Object.values(workerConfig).some((value) => !value))
    throw new Error(
      "Complete ledger worker deployment configuration is required",
    );
  new CellLedger(app, "CellLedger", {
    stage,
    tenant,
    worker: workerConfig
      ? {
          ...workerConfig,
          reserveConcurrency:
            app.node.tryGetContext("ledgerUseUnreserved") !== "true",
        }
      : undefined,
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("cellFhirDemo") === "true") {
  const expiresAt = process.env.VERIMED_FHIR_EXPIRES_AT;
  if (!expiresAt) throw new Error("Provide the approved FHIR demo expiry");
  new CellFhirDemo(app, "CellFhirDemo", {
    expiresAt,
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("cellWorklist") === "true") {
  const bundle = process.env.VERIMED_API_BUNDLE;
  const issuer = process.env.AUTH_COGNITO_ISSUER;
  const clientId = process.env.AUTH_COGNITO_ID;
  const tenantId = process.env.VERIMED_TENANT_ID;
  if (!bundle || !issuer || !clientId || !tenantId)
    throw new Error("Worklist deployment configuration is required");
  new CellWorklist(app, "CellWorklist", {
    bundle,
    issuer,
    clientId,
    tenantId,
    fhir:
      process.env.FHIR_ENDPOINT &&
      process.env.FHIR_DATASTORE_ARN &&
      process.env.VERIMED_FHIR_EXPIRES_AT
        ? {
            endpoint: process.env.FHIR_ENDPOINT,
            arn: process.env.FHIR_DATASTORE_ARN,
            expiresAt: process.env.VERIMED_FHIR_EXPIRES_AT,
            keyArn:
              process.env.FHIR_KMS_KEY_ARN ??
              (() => {
                throw new Error(
                  "FHIR_KMS_KEY_ARN is required for encrypted FHIR reads",
                );
              })(),
          }
        : undefined,
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("cellIdentity") === "true") {
  new CellIdentity(app, "CellIdentity", {
    demoWithoutMfa: app.node.tryGetContext("demoWithoutMfa") === "true",
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("agentCoreSpike") === "true") {
  const bundle = process.env.VERIMED_AGENTCORE_BUNDLE;
  const profileId = process.env.MODEL_CHALLENGER_ID;
  const modelArns = process.env.VERIMED_SPIKE_MODEL_ARNS?.split(",");
  if (!bundle || !profileId || !modelArns?.length) {
    throw new Error(
      "Provide the temporary Runtime bundle and Bedrock inference profile configuration",
    );
  }
  new AgentCoreSpike(app, "AgentCoreSpike", {
    bundle,
    profileId,
    modelArns,
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("fhirSpike") === "true") {
  new FhirSpike(app, "FhirSpike", {
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("healthscribeSpike") === "true") {
  new HealthScribeSpike(app, "HealthScribeSpike", {
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}
if (app.node.tryGetContext("liteLlmSpike") === "true") {
  new LiteLlmSpike(app, "LiteLlmSpike", {
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}

if (app.node.tryGetContext("hubCks") === "true") {
  const bundle = process.env.VERIMED_CKS_BUNDLE;
  const hub = process.env.VERIMED_HUB_ACCOUNT;
  const cell = process.env.VERIMED_CELL_ACCOUNT;
  const config = process.env.VERIMED_CKS_CALLERS_FILE;
  const cacheMajorVersion = process.env.CKS_CACHE_MAJOR_VERSION;
  if (!bundle || !hub || !cell || hub === cell || !config || !cacheMajorVersion)
    throw new Error(
      "Separate hub/cell accounts, CKS bundle and explicit callers file are required",
    );
  const callers = JSON.parse(readFileSync(config, "utf8")) as CksCaller[];
  new HubCKS(app, "HubCKS", {
    bundle,
    stage,
    cacheMajorVersion,
    callers,
    env: { region, account: hub },
  });
}

if (app.node.tryGetContext("cellFhirImport") === "true") {
  const datastoreArn = process.env.FHIR_DATASTORE_ARN;
  if (!datastoreArn)
    throw new Error(
      "FHIR_DATASTORE_ARN is required for the existing import destination",
    );
  new CellFhirImport(app, "CellFhirImport", {
    datastoreArn,
    stage,
    tenant,
    env: { region, account: process.env.VERIMED_CELL_ACCOUNT },
  });
}

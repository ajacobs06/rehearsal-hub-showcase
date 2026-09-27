// Rehearsal Hub infrastructure. Deploy:
//   az deployment group create -g rg-rehearsal-hub -f infra/main.bicep -p infra/main.bicepparam
// App settings are owned here: a redeploy replaces the full set, so never add settings by hand.
// Secrets live in Key Vault and are referenced from app settings.

@description('France Central (EU). UK South and UK West had no free App Service or Cosmos capacity for a new subscription.')
param location string = 'francecentral'

@description('Web app name, which is also the address: https://<appName>.azurewebsites.net. Globally unique; fixed once created.')
param appName string

@description('Budget alerts go here (at $5 and $20 actual spend a month).')
param budgetEmail string

@description('First day of the month the budget starts, e.g. 2026-10-01. Fixed once created.')
param budgetStartDate string

@description('Object ID of the developer, granted access to the dev database and Key Vault secrets.')
param developerPrincipalId string

@description('GitHub repository allowed to deploy, as its OIDC subject prefix. GitHub uses immutable IDs (owner@id/repo@id), so a renamed or re-created repo with the same name cannot match. See `gh api repos/{owner}/{repo}/actions/oidc/customization/sub`.')
param githubSubjectPrefix string = 'repo:ajacobs06@222806665/rehearsal-hub@1388325836'

@description('Google OAuth client ID. Leave empty to deploy without sign-in enabled.')
param googleClientId string = ''

@description('Entra External ID tenant (email and password sign-in) ID. Leave empty to offer Google only.')
param entraTenantId string = ''

@description('Client ID of the Rehearsal Hub app registration in that external tenant.')
param entraClientId string = ''

var entraEnabled = !empty(entraTenantId) && !empty(entraClientId)

var suffix = uniqueString(resourceGroup().id)

// Built-in role and Cosmos data-plane role IDs.
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var keyVaultSecretsOfficer = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var cosmosDataContributor = '00000000-0000-0000-0000-000000000002'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageBlobDelegator = 'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'
var websiteContributor = 'de139f84-1756-47ae-9be6-808fbbe84772'

// ---------- Web app ----------

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'asp-rehearsal-hub'
  location: location
  kind: 'linux'
  sku: {
    name: 'F1'
    tier: 'Free'
  }
  properties: {
    reserved: true
  }
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      // Dependencies come prebuilt in pydeps/ (see PYTHONPATH below and the deploy workflow).
      appCommandLine: 'python -m gunicorn -w 2 -k worker.Worker main:app'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
  }
}

resource appSettings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: site
  name: 'appsettings'
  properties: union({
    // Never build on App Service: an Oryx pip install can use up the free plan's daily CPU quota
    // (it did on the first deploy here). GitHub Actions ships the dependencies in pydeps/.
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'false'
    ENABLE_ORYX_BUILD: 'false'
    PYTHONPATH: '/home/site/wwwroot/pydeps'
    APP_URL: 'https://${site.properties.defaultHostName}'
    COSMOS_ENDPOINT: cosmos.properties.documentEndpoint
    COSMOS_DATABASE: prodDb.name
    EMAIL_SENDER: 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}'
    ACS_CONNECTION_STRING: '@Microsoft.KeyVault(VaultName=${vault.name};SecretName=${acsSecret.name})'
    GOOGLE_PROVIDER_AUTHENTICATION_SECRET: '@Microsoft.KeyVault(VaultName=${vault.name};SecretName=google-client-secret)'
    STORAGE_ACCOUNT_URL: storage.properties.primaryEndpoints.blob
    TRACKS_CONTAINER: tracksContainer.name
    APPLICATIONINSIGHTS_CONNECTION_STRING: insights.properties.ConnectionString
  }, entraEnabled ? {
    // The API only trusts "aad" sign-ins from this tenant (api/auth.py).
    ENTRA_TENANT_ID: entraTenantId
    MICROSOFT_PROVIDER_AUTHENTICATION_SECRET: '@Microsoft.KeyVault(VaultName=${vault.name};SecretName=entra-client-secret)'
  } : {})
  dependsOn: [appVaultAccess]
}

// No basic-auth publishing: GitHub Actions deploys with OIDC as the identity below.
resource scmPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: site
  name: 'scm'
  properties: {
    allow: false
  }
}

resource ftpPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: site
  name: 'ftp'
  properties: {
    allow: false
  }
}

// ---------- Deploy identity (GitHub Actions OIDC, no stored secret) ----------
// A user-assigned identity instead of an app registration: no secret to rotate. It trusts only
// jobs in this repo's `production` environment and can only manage this web app.

resource deployIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-rehearsal-hub-deploy'
  location: location
}

resource deployFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: deployIdentity
  name: 'github-production'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: '${githubSubjectPrefix}:environment:production'
    audiences: ['api://AzureADTokenExchange']
  }
}

resource deployAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: site
  name: guid(site.id, deployIdentity.id, websiteContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', websiteContributor)
    principalId: deployIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output deployClientId string = deployIdentity.properties.clientId

// Easy Auth: Google sign-in, plus email and password through our Entra External ID tenant. Anonymous requests are allowed so the app shell and /api/health load;
// the API decides per endpoint. Easy Auth strips client-supplied X-MS-CLIENT-PRINCIPAL headers.
resource auth 'Microsoft.Web/sites/config@2023-12-01' = if (!empty(googleClientId)) {
  parent: site
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      requireAuthentication: false
      unauthenticatedClientAction: 'AllowAnonymous'
    }
    identityProviders: union({
      google: {
        enabled: true
        registration: {
          clientId: googleClientId
          clientSecretSettingName: 'GOOGLE_PROVIDER_AUTHENTICATION_SECRET'
        }
        login: {
          scopes: ['openid', 'email', 'profile']
        }
      }
    }, entraEnabled ? {
      // Pinned to our external tenant's issuer, so work or school accounts from other tenants can't sign in.
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://${entraTenantId}.ciamlogin.com/${entraTenantId}/v2.0'
          clientId: entraClientId
          clientSecretSettingName: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
        }
        login: {
          loginParameters: ['scope=openid profile email']
        }
        validation: {
          allowedAudiences: [entraClientId]
        }
      }
    } : {})
    login: {
      // The app never uses provider tokens; keeping them would expose them via /.auth/me.
      tokenStore: {
        enabled: false
      }
    }
  }
  dependsOn: [appSettings]
}

// ---------- Cosmos DB (free tier) ----------

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-rehearsal-hub-${suffix}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: true
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    // Free tier covers 1000 RU/s; cap it so the account can never bill for throughput.
    capacity: {
      totalThroughputLimit: 1000
    }
  }
}

resource prodDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'rehearsal-hub'
  properties: {
    resource: {
      id: 'rehearsal-hub'
    }
    options: {
      throughput: 600
    }
  }
}

resource devDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'rehearsal-hub-dev'
  properties: {
    resource: {
      id: 'rehearsal-hub-dev'
    }
    options: {
      throughput: 400
    }
  }
}

resource prodMembers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: prodDb
  name: 'members'
  properties: {
    resource: {
      id: 'members'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource devMembers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: devDb
  name: 'members'
  properties: {
    resource: {
      id: 'members'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource prodSongs 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: prodDb
  name: 'songs'
  properties: {
    resource: {
      id: 'songs'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource devSongs 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: devDb
  name: 'songs'
  properties: {
    resource: {
      id: 'songs'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource prodProgress 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: prodDb
  name: 'progress'
  properties: {
    resource: {
      id: 'progress'
      partitionKey: {
        paths: ['/songId']
        kind: 'Hash'
      }
    }
  }
}

resource devProgress 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: devDb
  name: 'progress'
  properties: {
    resource: {
      id: 'progress'
      partitionKey: {
        paths: ['/songId']
        kind: 'Hash'
      }
    }
  }
}

resource prodRehearsals 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: prodDb
  name: 'rehearsals'
  properties: {
    resource: {
      id: 'rehearsals'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource devRehearsals 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: devDb
  name: 'rehearsals'
  properties: {
    resource: {
      id: 'rehearsals'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource prodGroups 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: prodDb
  name: 'groups'
  properties: {
    resource: {
      id: 'groups'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource devGroups 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: devDb
  name: 'groups'
  properties: {
    resource: {
      id: 'groups'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource prodFeedback 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: prodDb
  name: 'feedback'
  properties: {
    resource: {
      id: 'feedback'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource devFeedback 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: devDb
  name: 'feedback'
  properties: {
    resource: {
      id: 'feedback'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

resource appCosmosAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, site.id, cosmosDataContributor)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    principalId: site.identity.principalId
    scope: '${cosmos.id}/dbs/${prodDb.name}'
  }
}

resource devCosmosAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, developerPrincipalId, cosmosDataContributor)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    principalId: developerPrincipalId
    scope: '${cosmos.id}/dbs/${devDb.name}'
  }
}

// ---------- Blob Storage (tracks and scores) ----------
// No public access and no shared keys: the browser gets per-blob user delegation SAS links
// signed with the web app's managed identity, and talks to Blob Storage directly.

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'strh${suffix}'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    // Every overwrite keeps the previous version, so a replaced score can be recovered
    // (old versions are removed after 30 days by the lifecycle rule below).
    isVersioningEnabled: true
    cors: {
      corsRules: [
        {
          // Production only: local dev uses its own account (devStorage below).
          allowedOrigins: ['https://${site.properties.defaultHostName}']
          allowedMethods: ['GET', 'HEAD', 'PUT', 'OPTIONS']
          allowedHeaders: ['*']
          exposedHeaders: ['*']
          maxAgeInSeconds: 3600
        }
      ]
    }
  }
}

resource versionCleanup 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-old-versions'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
            }
            actions: {
              version: {
                delete: {
                  daysAfterCreationGreaterThan: 30
                }
              }
            }
          }
        }
      ]
    }
  }
}

resource tracksContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'tracks'
  properties: {
    publicAccess: 'None'
  }
}

// User delegation keys are issued at account level; data access is scoped to one container each.
resource appBlobDelegator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, site.id, storageBlobDelegator)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDelegator)
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource appTracksAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: tracksContainer
  name: guid(tracksContainer.id, site.id, storageBlobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------- Dev Blob Storage (local development only) ----------
// A separate account so the production account's CORS trusts only the live site, and the developer
// has no role on the production account at all.

resource devStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'strhdev${take(suffix, 13)}'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource devBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: devStorage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    cors: {
      corsRules: [
        {
          allowedOrigins: ['http://localhost:5173']
          allowedMethods: ['GET', 'HEAD', 'PUT', 'OPTIONS']
          allowedHeaders: ['*']
          exposedHeaders: ['*']
          maxAgeInSeconds: 3600
        }
      ]
    }
  }
}

resource devTracksContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: devBlobService
  name: 'tracks-dev'
  properties: {
    publicAccess: 'None'
  }
}

resource devBlobDelegator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: devStorage
  name: guid(devStorage.id, developerPrincipalId, storageBlobDelegator)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDelegator)
    principalId: developerPrincipalId
    principalType: 'User'
  }
}

resource devTracksAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: devTracksContainer
  name: guid(devTracksContainer.id, developerPrincipalId, storageBlobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: developerPrincipalId
    principalType: 'User'
  }
}

output devStorageUrl string = devStorage.properties.primaryEndpoints.blob

// ---------- Error monitoring (server-side only) ----------
// Free tier with a hard daily cap so it can never bill; App Insights masks client IPs by default.

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-rehearsal-hub-${suffix}'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: json('0.1')
    }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-rehearsal-hub-${suffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    IngestionMode: 'LogAnalytics'
    RetentionInDays: 30
  }
}

// ---------- Email (Azure Communication Services) ----------

resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: 'email-rehearsal-hub-${suffix}'
  location: 'global'
  properties: {
    dataLocation: 'Europe'
  }
}

resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: 'acs-rehearsal-hub-${suffix}'
  location: 'global'
  properties: {
    dataLocation: 'Europe'
    linkedDomains: [emailDomain.id]
  }
}

// ---------- Key Vault ----------

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-rh-${take(suffix, 13)}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
    // Permanent once on: deleted secrets can't be purged early, so they can always be recovered.
    enablePurgeProtection: true
  }
}

resource acsSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'acs-connection-string'
  properties: {
    value: acs.listKeys().primaryConnectionString
  }
}

resource appVaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, site.id, keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource devVaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, developerPrincipalId, keyVaultSecretsOfficer)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficer)
    principalId: developerPrincipalId
    principalType: 'User'
  }
}

output name string = site.name
output defaultHostname string = site.properties.defaultHostName
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output keyVaultName string = vault.name
output storageUrl string = storage.properties.primaryEndpoints.blob
output emailSender string = 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}'

// ---------- Audit logs ----------
// Who changed data or read secrets, kept 30 days in the capped workspace. Blob reads (every audio
// stream) and Cosmos data-plane requests are left out: too many for the 0.1 GB/day cap.

resource vaultAudit 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: vault
  name: 'audit-to-log-analytics'
  properties: {
    workspaceId: logs.id
    logs: [
      {
        category: 'AuditEvent'
        enabled: true
      }
    ]
  }
}

resource blobAudit 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blobService
  name: 'audit-to-log-analytics'
  properties: {
    workspaceId: logs.id
    logs: [
      {
        category: 'StorageWrite'
        enabled: true
      }
      {
        category: 'StorageDelete'
        enabled: true
      }
    ]
  }
}

resource cosmosAudit 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: cosmos
  name: 'audit-to-log-analytics'
  properties: {
    workspaceId: logs.id
    logs: [
      {
        category: 'ControlPlaneRequests'
        enabled: true
      }
    ]
  }
}

// ---------- Budget ----------
// Pay-As-You-Go bills real money, so alert well before anything costs much. Everything here is
// meant to stay on free tiers; any spend at all means something has changed.

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: 'rehearsal-hub-monthly'
  properties: {
    category: 'Cost'
    amount: 20
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      actual_5usd: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 25
        contactEmails: [budgetEmail]
      }
      actual_20usd: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        contactEmails: [budgetEmail]
      }
      forecast_20usd: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [budgetEmail]
      }
    }
  }
}

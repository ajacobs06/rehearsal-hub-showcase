// Free (F1) Linux App Service hosting the FastAPI backend and the built React front end.
// Deploy: az deployment group create -g rg-rehearsal-hub -f infra/main.bicep

@description('The Azure for Students subscription only allows a few EU regions; France Central is the closest.')
param location string = 'francecentral'

param name string = 'rehearsal-hub-${uniqueString(resourceGroup().id)}'

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
  name: name
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
      appCommandLine: 'gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
      ]
    }
  }
}

// GitHub Actions deploys with the publish profile, which needs SCM basic auth.
resource scmPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: site
  name: 'scm'
  properties: {
    allow: true
  }
}

output name string = site.name
output defaultHostname string = site.properties.defaultHostName

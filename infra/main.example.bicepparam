using 'main.bicep'

// Example values only. Copy to main.bicepparam (gitignored) and fill in your own before deploying:
//   az deployment group create -g <resource-group> -f infra/main.bicep -p infra/main.bicepparam
param developerPrincipalId = '<your-entra-object-id>'
param appName = '<globally-unique-app-name>'
param budgetEmail = 'alerts@example.com'
param budgetStartDate = '2026-10-01'
// Optional: leave empty to deploy without that sign-in option.
param googleClientId = '<google-client-id>.apps.googleusercontent.com'
param entraTenantId = '<entra-external-id-tenant-id>'
param entraClientId = '<entra-app-client-id>'
param entraCleanupClientId = '<entra-cleanup-app-client-id>'

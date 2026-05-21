# Auto-Deployment for JavaAPEX Microservice Generation

## Overview

Auto-deployment automatically deploys your generated microservices to Render.com immediately after conversion. This eliminates the need for manual deployment steps and gets your services live in minutes.

## Quick Start

### Prerequisites

Before enabling auto-deployment, ensure you have:

1. **Render.com Account**: Create one at https://render.com
2. **Render API Key**: Get it from https://dashboard.render.com/api-tokens
3. **GitHub Repository**: Your microservices code pushed to GitHub
4. **Python 3.8+**: Already required for the project

### Enable Auto-Deployment

Set these environment variables before running the microservice conversion:

```bash
# Your Render.com API key (from dashboard)
export RENDER_API_KEY="your-render-api-key-here"

# Your GitHub repository in format: owner/repo
export GITHUB_REPOSITORY="your-username/your-repo-name"

# Enable automatic deployment
export AUTO_DEPLOY="true"
```

### Generate and Deploy

When you generate microservices with auto-deployment enabled:

```bash
# Linux/macOS
RENDER_API_KEY="your-key" GITHUB_REPOSITORY="owner/repo" AUTO_DEPLOY="true" python3 main.py

# PowerShell (Windows)
$env:RENDER_API_KEY="your-key"
$env:GITHUB_REPOSITORY="owner/repo"
$env:AUTO_DEPLOY="true"
python3 main.py
```

The system will:
1. Generate your microservices
2. Create LLM-optimized deployment configurations
3. **Automatically deploy all services to Render.com**
4. Provide deployment status and service URLs

## How Auto-Deployment Works

### Process Flow

```
User Initiates Conversion
    ↓
[Check AUTO_DEPLOY environment variable]
    ↓
If AUTO_DEPLOY=true:
    ├─ Verify RENDER_API_KEY is set
    ├─ Verify GITHUB_REPOSITORY is set
    ├─ Generate render_deploy.py script
    └─ Execute deployment automatically
    ↓
[Deployment Results]
    ├─ Success: Services are live on Render.com
    ├─ Failed: Error details provided in logs
    └─ Skipped: If AUTO_DEPLOY not enabled (manual deployment available)
```

### What Gets Deployed

For each generated microservice:

- **Web Service**: Deployed to Render.com with LLM-optimized configuration
  - Memory allocation (typically 256-1024 MB)
  - CPU allocation (0.25-1 core)
  - Environment variables configured
  - Auto-scaling enabled (1-3+ instances)

- **Database** (if service has entities):
  - PostgreSQL database automatically provisioned
  - Connection details automatically configured
  - Backups enabled by default

- **Health Checks**: Configured for monitoring
  - REST endpoint monitoring
  - Auto-recovery on failures

- **API Gateway**: Provides single entry point to all services
  - Routes requests to appropriate microservices
  - Load balancing and failover

## Monitoring Deployment

### Real-Time Logs

During auto-deployment, the terminal will show:

```
[Render Deploy] Deploying services for my-project...
[Render Deploy] Creating service: order-service
[Render Deploy]   ✓ Service created: svc_abc123
[Render Deploy]   Creating database for order-service...
[Render Deploy]   ✓ Database created: db_xyz789
[Render Deploy] Creating service: inventory-service
[Render Deploy]   ✓ Service created: svc_def456
...
[Render Deploy] Deployment complete! Services are starting up on Render.com
```

### Render Dashboard

After deployment, monitor your services:

1. Go to: https://dashboard.render.com/services
2. View each service:
   - Real-time logs
   - Resource usage (CPU, memory)
   - Deployment status
   - Scaling events

3. Access your services:
   - **API Gateway**: `https://your-project-api-gateway.onrender.com`
   - **Individual Service**: `https://your-project-service-name.onrender.com`
   - **Health Check**: `https://service-url/actuator/health`

## Deployment Configuration

The system automatically generates optimal configurations based on your services:

### Per-Service Analysis

For each microservice, the LLM analyzes:

- **Service Complexity**: Number of entities, controllers, repositories
- **Data Requirements**: Database needs based on entities
- **Messaging**: Message queue requirements
- **Resource Allocation**: Recommended memory/CPU based on complexity
- **Scaling**: Min/max instances for auto-scaling

### Generated Configuration Example

```json
{
  "services": {
    "order-service": {
      "memory_mb": 512,
      "cpu_cores": 0.5,
      "environment": {
        "SPRING_PROFILES_ACTIVE": "production",
        "EUREKA_CLIENT_SERVICEURL_DEFAULTZONE": "https://eureka.render.com/eureka/"
      },
      "database": {
        "type": "postgresql",
        "auto_provision": true
      },
      "health_check": {
        "path": "/actuator/health",
        "interval_seconds": 30
      },
      "auto_scale": {
        "enabled": true,
        "min_instances": 1,
        "max_instances": 3
      }
    }
  }
}
```

## Troubleshooting Auto-Deployment

### Issue: "RENDER_API_KEY not set"

**Solution**: Set the environment variable before running conversion

```bash
export RENDER_API_KEY="your-actual-api-key"
```

Get your API key from: https://dashboard.render.com/api-tokens

### Issue: "GITHUB_REPOSITORY not set"

**Solution**: Set your GitHub repository in the format `owner/repo`

```bash
export GITHUB_REPOSITORY="your-username/your-repo"
```

### Issue: "Auto-deployment skipped"

This occurs when `AUTO_DEPLOY` is not set to `true`. If you want to enable it:

```bash
export AUTO_DEPLOY="true"
```

Then generate the microservices again.

### Issue: Service deployment fails

Check the deployment script output for specific errors:

```bash
# Run manual deployment to see detailed errors
cd render-deployment
python3 render_deploy.py
```

Common issues:
- **Invalid API key**: Verify key in Render dashboard
- **Service name conflict**: Use unique service names
- **Quota limits**: Check Render.com account limits
- **Network issues**: Check internet connectivity

### Issue: Database fails to create

Ensure the service has `has_database: true` in the configuration:

1. Check `render-deployment/deployment-config.json`
2. Verify `has_database` field
3. Check Render.com account has database quota

## Manual Deployment (Alternative)

If auto-deployment is disabled or fails, deploy manually:

```bash
cd render-deployment
export RENDER_API_KEY="your-key"
export GITHUB_REPOSITORY="owner/repo"
python3 render_deploy.py
```

## Cost Optimization

Auto-deployment uses cost-optimized configurations:

- **Minimum instances**: 1 (scales up on demand)
- **Memory allocation**: Based on service analysis (not over-provisioned)
- **Auto-scaling**: Prevents unnecessary resource usage
- **Databases**: Standard tier with backups

**Estimated cost**: $5-15/month for typical 3-4 service system

Check Render.com pricing: https://render.com/pricing

## CI/CD Integration

For automated deployment on each code push, integrate with GitHub Actions:

1. Add deployment script to GitHub Actions workflow
2. Set `RENDER_API_KEY` as a GitHub secret
3. Trigger deployment on push to main branch

Example workflow:

```yaml
name: Auto-Deploy Microservices
on:
  push:
    branches: [main]
env:
  RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}
  GITHUB_REPOSITORY: ${{ github.repository }}
  AUTO_DEPLOY: "true"
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate and Deploy
        run: |
          python3 -m venv venv
          source venv/bin/activate
          pip install -r JavaAPEX-Backend/requirements.txt
          python3 JavaAPEX-Backend/main.py
```

## Deployment Workflow Files

Generated files in `render-deployment/`:

- **`render_deploy.py`**: Deployment script (auto-executed)
- **`deployment-config.json`**: LLM-optimized configurations
- **`README.md`**: Deployment documentation

All files are ready for immediate deployment or future reference.

## Next Steps After Deployment

1. **Monitor services** in Render.com dashboard
2. **Test API endpoints** with your API Gateway URL
3. **Configure custom domains** if needed
4. **Set up monitoring** and alerts in Render
5. **Review logs** for any deployment issues

## Support

For issues with:

- **Auto-deployment logic**: Check logs in JavaAPEX-Backend
- **Render.com deployment**: See Render docs: https://docs.render.com
- **Service configuration**: Review generated deployment-config.json
- **GitHub integration**: Check GitHub Actions logs

## Performance Metrics

Typical auto-deployment timeline:

- Service generation: 2-5 minutes
- Auto-deployment execution: 3-8 minutes
- Service startup on Render: 2-5 minutes
- **Total time from conversion to live**: 7-18 minutes

Services will scale automatically based on traffic and resource usage.

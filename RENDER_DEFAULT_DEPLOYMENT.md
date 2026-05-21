# Render.com Deployment (Default Workflow)

## Overview

Your microservice generation system now automatically creates **Render.com deployment** as the **DEFAULT deployment workflow** for all generated microservices.

**What This Means:**
- Every microservice generation automatically includes Render deployment configuration
- LLM analyzes services and optimizes resource allocation automatically
- One simple command deploys all services to Render.com
- No GitHub Actions or additional CI/CD setup required (but can be added optionally)

## What Gets Generated

When you generate microservices, you automatically get:

```
output-project/
├── render-deployment/                    ← DEFAULT DEPLOYMENT FOLDER
│   ├── render_deploy.py                  ← Deployment script
│   ├── deployment-config.json            ← LLM-optimized configs
│   └── README.md                         ← Detailed deployment guide
├── pom.xml                               ← Parent build
├── docker-compose.yml                    ← Local development
├── README.md                             ← Updated with Render info
├── api-gateway/                          ← Gateway service
├── [service-1]/                          ← Your microservices
├── [service-n]/
└── shared-common/                        ← Shared libraries
```

## Quick Start

### 1. Generate Microservices

```bash
POST /api/microservice-conversion/convert
```

### 2. Navigate to Render Deployment

```bash
cd output-project/render-deployment
```

### 3. Set Environment Variables

```bash
export RENDER_API_KEY="your-render-api-key"  # Get from https://dashboard.render.com/api-tokens
export GITHUB_REPOSITORY="owner/repo-name"   # Your GitHub repo path
```

### 4. Deploy

```bash
python3 render_deploy.py
```

### 5. Monitor

```
https://dashboard.render.com/services
```

## What Happens During Deployment

1. **Configuration Analysis**
   - LLM analyzes your microservices architecture
   - Determines optimal resource allocation per service
   - Generates deployment configuration

2. **Service Creation**
   - Creates web service for each microservice
   - Sets up API Gateway
   - Configures Eureka service discovery

3. **Database Provisioning**
   - PostgreSQL databases auto-created for services with data
   - Connection strings automatically injected

4. **Health Monitoring**
   - Health checks configured on `/actuator/health`
   - Automatic service restart on failure

5. **Auto-scaling**
   - Each service scales based on LLM analysis
   - Min/max instances set based on service criticality

## Generated Configuration

The LLM automatically generates optimal configurations:

### Memory Allocation
- **Simple services** (no database): 256-512 MB
- **Data services** (with database): 512-768 MB
- **Critical services** (payment, orders): 768-1024 MB

### CPU Cores
- Scaled from 0.25 to 1.0 based on service type

### Auto-scaling
- **Min instances**: 1-2 (based on service importance)
- **Max instances**: 3-8 (based on expected load)

### Environment Variables
```
SPRING_PROFILES_ACTIVE=production
EUREKA_CLIENT_SERVICEURL_DEFAULTZONE=https://eureka.render.com/eureka/
LOG_LEVEL=INFO
```

## Example Generated Configuration

For a project with 3 microservices, the deployment configuration looks like:

```json
{
  "services": {
    "order-service": {
      "memory_mb": 768,
      "cpu_cores": 0.75,
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
        "min_instances": 2,
        "max_instances": 5
      }
    },
    "user-service": {
      "memory_mb": 512,
      "cpu_cores": 0.5,
      "database": {
        "type": "postgresql",
        "auto_provision": true
      },
      "auto_scale": {
        "enabled": true,
        "min_instances": 1,
        "max_instances": 3
      }
    }
  },
  "shared_services": {
    "eureka": {
      "memory_mb": 256,
      "cpu_cores": 0.25
    },
    "api_gateway": {
      "memory_mb": 512,
      "cpu_cores": 0.5
    }
  }
}
```

## Deployment Process

### Step 1: Review Configuration

```bash
cat deployment-config.json | jq .
```

Edit if needed (optional)

### Step 2: Deploy

```bash
python3 render_deploy.py
```

Output:
```
Deploying services for my-project...
Creating service: order-service
  ✓ Service created: abc123xyz
  Creating database for order-service...
  ✓ Database created: postgres-789
Creating service: user-service
  ✓ Service created: def456uvw
  Creating database for user-service...
  ✓ Database created: postgres-790

Deployment complete! Services are starting up on Render.com
View your services at: https://dashboard.render.com/services
```

### Step 3: Access Services

After deployment (usually 5-10 minutes):

- **API Gateway**: `https://my-project-api-gateway.onrender.com`
- **Order Service**: `https://my-project-order-service.onrender.com`
- **User Service**: `https://my-project-user-service.onrender.com`

## Prerequisites

- Render.com account (free tier available): https://render.com
- Render API key: https://dashboard.render.com/api-tokens
- Python 3.8+

## Monitoring Your Services

### Render.com Dashboard

```
https://dashboard.render.com/services
```

Features:
- Real-time service status
- CPU/Memory usage graphs
- Service logs
- Deployment history
- Scaling events

### Service Logs

```bash
# In Render dashboard:
1. Click service name
2. Click "Logs" tab
3. View real-time logs
```

### Health Checks

```bash
# Check service health
curl https://service-name.onrender.com/actuator/health

# Check database connection
curl https://service-name.onrender.com/actuator/db
```

## Customizing Deployment

### Edit Resource Allocation

Edit `deployment-config.json`:

```json
{
  "services": {
    "my-service": {
      "memory_mb": 768,        ← Change here
      "cpu_cores": 0.75,       ← Or here
      "auto_scale": {
        "min_instances": 2,    ← Or here
        "max_instances": 5     ← Or here
      }
    }
  }
}
```

Then redeploy:

```bash
python3 render_deploy.py
```

### Add Environment Variables

```json
{
  "services": {
    "my-service": {
      "environment": {
        "MY_VAR": "value",
        "LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```

### Disable Auto-scaling

```json
{
  "services": {
    "my-service": {
      "auto_scale": {
        "enabled": false,
        "min_instances": 1
      }
    }
  }
}
```

## Troubleshooting

### Issue: RENDER_API_KEY not set

```bash
export RENDER_API_KEY="your-key-from-render-dashboard"
python3 render_deploy.py
```

### Issue: Service creation fails

Check in Render dashboard:
1. Go to https://dashboard.render.com
2. Check "Events" tab for error messages
3. Verify API key permissions
4. Ensure service name is unique

### Issue: Database connection fails

```bash
# Check connection string in service logs
1. Go to Render dashboard
2. Click service → Logs tab
3. Look for PostgreSQL connection errors
4. Verify database credentials
```

### Issue: Service won't start

```bash
# Check application logs
https://dashboard.render.com/services
  → Click service name
  → Logs tab
  → Look for Spring Boot startup errors
```

Common causes:
- Application port conflicts
- Missing environment variables
- Database not yet provisioned (wait a few seconds)

## Manual Service Creation (Advanced)

If needed, you can modify `deployment-config.json` and redeploy:

```bash
# Edit configuration
nano deployment-config.json

# Verify JSON is valid
jq . deployment-config.json

# Redeploy
python3 render_deploy.py
```

## Cost Optimization

Default configuration minimizes costs:

- **Minimum instances**: Start at 1 (scales on demand)
- **Memory/CPU**: Sized based on service analysis
- **Auto-scaling**: Prevents overallocation

Monthly cost estimate:
- 3 services @ $7/month each = $21
- Eureka + Gateway = $14
- 3 PostgreSQL DBs @ $15/month each = $45
- **Total**: ~$80/month (can be less with free tier)

Check Render pricing: https://render.com/pricing

## CI/CD Integration (Optional)

Want automatic deployment on git push?

You can add GitHub Actions that calls `render_deploy.py`:

```yaml
# In .github/workflows/deploy.yml
- name: Deploy to Render
  env:
    RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}
  run: python3 render-deployment/render_deploy.py
```

This is optional - the deployment script works manually too.

## Deployment Workflow Comparison

### Before (With GitHub Actions)
```
Code Push → GitHub Actions → Build → Deploy → Render
(Complex setup, multiple tools)
```

### Now (Default Render Workflow)
```
Code Push → Run render_deploy.py → Services Live
(Simple, direct deployment)
```

Both approaches work. **Render deployment is now the DEFAULT and recommended approach.**

## Key Benefits

✓ **Simple** - One command deploys all services
✓ **Automatic** - LLM optimizes everything
✓ **Fast** - ~20 minutes from generation to live
✓ **Cost-effective** - Right-sized resources
✓ **Observable** - Built-in health checks and monitoring
✓ **Scalable** - Auto-scales based on load

## Next Steps

1. Generate microservices with the system
2. Navigate to `render-deployment` folder
3. Get Render API key from dashboard
4. Run deployment script
5. Monitor in Render.com dashboard
6. Access your live services!

## Support

- Render.com docs: https://render.com/docs
- Render API: https://render.com/docs/api-reference
- Spring Boot Actuator: https://spring.io/guides/gs/actuator-service/

---

**Render.com deployment is your DEFAULT production workflow.**
Everything is automated - just run the script!

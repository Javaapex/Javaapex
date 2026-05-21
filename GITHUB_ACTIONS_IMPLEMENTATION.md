# GitHub Actions & Render.com Deployment Implementation

## Overview

The JavaAPEX-Backend microservice generation system has been enhanced to automatically generate GitHub Actions workflows that deploy microservices to Render.com with LLM-powered configuration analysis.

## What's Been Implemented

### 1. **GitHub Actions Workflow Generation** (`.github/workflows/render-service.yml`)

The system now generates a complete GitHub Actions workflow that:

- **Analyzes service configurations** using LLM to determine optimal deployment settings
- **Builds each microservice** independently using Maven
- **Creates Docker images** for each service
- **Pushes images** to GitHub Container Registry (ghcr.io)
- **Deploys to Render.com** with LLM-analyzed configurations
- **Provides health checks** and monitoring

#### Workflow Triggers

The workflow automatically runs when:
- Code is pushed to `main` or `develop` branches
- Changes to Java files, pom.xml, or workflow files are detected
- Manually triggered via GitHub Actions UI (`workflow_dispatch`)

#### Workflow Jobs

1. **analyze-config**: Analyzes service architecture and creates deployment configurations
2. **Service Build Jobs** (one per microservice): Builds, tests, and pushes Docker images
3. **deploy-to-render**: Deploys all services to Render.com
4. **status-check**: Provides deployment summary

### 2. **LLM-Based Configuration Analysis** (`_generate_service_deployment_config()`)

Uses AI to analyze each microservice and determine:

- **Memory allocation**: Based on service complexity and database requirements
- **CPU cores**: Scaled according to expected workload
- **Environment variables**: Production-ready configurations
- **Database configuration**: Automatic PostgreSQL provisioning
- **Health check endpoints**: REST endpoints for monitoring
- **Auto-scaling settings**: Min/max instances based on service characteristics
- **Build and start commands**: Optimized JVM arguments

Example generated configuration:
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
  },
  "shared_services": {
    "eureka": { "memory_mb": 256, "cpu_cores": 0.25 },
    "api_gateway": { "memory_mb": 512, "cpu_cores": 0.25 }
  }
}
```

### 3. **Render.com Deployment Script** (`scripts/render_deploy.py`)

Automatically generated Python script that:

- Reads LLM-analyzed deployment configuration
- Creates services on Render.com using their API
- Provisions databases as needed
- Sets environment variables
- Configures health checks
- Enables auto-scaling

The script uses the Render.com REST API to:
```python
POST /v1/services       # Create web services
POST /v1/postgres       # Create PostgreSQL databases
```

### 4. **Documentation** (`.github/workflows/README.md`)

Comprehensive guide including:
- Feature overview
- Required GitHub secrets
- Deployment process explanation
- Manual deployment instructions
- Monitoring dashboard links
- Troubleshooting guide

## Generated File Structure

```
output-microservices/
├── .github/
│   └── workflows/
│       ├── render-service.yml        # Main GitHub Actions workflow
│       └── README.md                  # Deployment documentation
├── scripts/
│   └── render_deploy.py               # Render.com deployment script
├── pom.xml                            # Parent Maven POM
├── docker-compose.yml                 # Local development setup
├── README.md                          # Project README with deployment info
├── api-gateway/
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/
├── service-1/
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/
├── service-2/
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/
└── ...
```

## Setup Instructions

### 1. Configure GitHub Secrets

Add these secrets to your GitHub repository settings:

```
RENDER_API_KEY        - Get from https://dashboard.render.com/api-tokens
LLM_API_KEY           - Your OpenAI-compatible LLM API key (optional, uses env vars as fallback)
```

### 2. GitHub Actions Configuration

The workflow is automatically configured to:
- Trigger on pushes to `main` and `develop` branches
- Build services with Maven cache enabled
- Push images to GitHub Container Registry
- Deploy only on `main` branch merges

### 3. Local Testing

Test the deployment script locally:
```bash
export RENDER_API_KEY="your-api-key"
export GITHUB_REPOSITORY="owner/repo"
python3 scripts/render_deploy.py
```

## Workflow Execution Flow

```
1. Code Push to main
   ↓
2. GitHub Actions Triggered
   ↓
3. analyze-config Job
   - Reads service metadata
   - Calls LLM to generate optimal configs
   - Outputs config JSON
   ↓
4. Parallel Build Jobs (one per service)
   - Checkout code
   - Setup JDK 17
   - Maven build
   - Docker image build
   - Push to ghcr.io
   ↓
5. deploy-to-render Job (waits for all builds)
   - Setup Python environment
   - Run render_deploy.py
   - Services created with LLM-analyzed configs
   ↓
6. status-check Job
   - Summarize deployment
   - Provide dashboard link
```

## Render.com Deployment Features

### Service Creation
- Services are created with LLM-optimized resource allocation
- Automatic Docker image deployment from GitHub Container Registry
- Branch-based deployments (main → production)

### Database Provisioning
- PostgreSQL databases auto-created for services with `has_database: true`
- Connection strings automatically injected as environment variables
- Credentials securely managed by Render.com

### Environment Configuration
- Production environment variables applied automatically
- Service discovery configured for microservices communication
- Spring profiles set to `production` for optimized behavior

### Health Monitoring
- Automatic health checks configured on `/actuator/health`
- Service crashes trigger automatic restart
- Render.com dashboard shows real-time status

### Auto-Scaling
- Services scale between min/max instances
- Scale-up triggered by CPU/memory usage
- Managed through Render.com's intelligent scaling

## LLM Analysis Benefits

The LLM-based configuration analysis provides:

1. **Intelligent Resource Allocation**
   - Services with databases get more memory
   - Messaging services get higher CPU allocation
   - Scaling recommendations based on complexity

2. **Production-Ready Defaults**
   - Security-focused environment variables
   - Optimized JVM options for containers
   - Health check paths auto-detected from Spring Boot actuator

3. **Service Interdependency**
   - LLM understands relationships between services
   - Configures networking appropriately
   - Sets up load balancing for high-traffic services

4. **Failure Prevention**
   - Detects services that need databases before provisioning
   - Validates health check endpoints exist
   - Ensures sufficient resource allocation

## Monitoring & Troubleshooting

### View Deployment Status
1. Go to GitHub Actions tab in your repository
2. Select the latest "Build and Deploy Microservices to Render.com" workflow run
3. View step-by-step build and deployment logs

### Monitor on Render.com
- Dashboard: https://dashboard.render.com/services
- View logs for each service
- Check deployment history and status

### Common Issues & Solutions

**Issue: RENDER_API_KEY not set**
- Solution: Add the secret to your GitHub repository settings
- Navigate to Settings → Secrets and variables → Actions

**Issue: Service creation fails**
- Check Render.com dashboard for quota limits
- Verify API key has necessary permissions
- Check service name uniqueness

**Issue: Build failures**
- Check Maven build logs in GitHub Actions
- Verify Java version compatibility (17+)
- Ensure all dependencies in pom.xml are correct

**Issue: Service startup fails**
- Check Spring Boot logs in Render.com dashboard
- Verify database connection string is correct
- Ensure environment variables are properly set

## Advanced Configuration

### Customizing LLM Analysis
The LLM configuration can be customized by modifying environment variables:
```bash
LLM_MODEL=gpt-4           # Use different model
LLM_BASE_URL=https://...  # Use different endpoint
LLM_SUB_MODEL=...         # Use routing hints
```

### Manual Service Configuration
For advanced use cases, directly edit the generated `scripts/render_deploy.py`:
- Modify resource allocation for specific services
- Add custom environment variables
- Configure advanced networking

### CI/CD Integration
The workflow can be extended to:
- Run integration tests before deployment
- Perform security scanning
- Update documentation automatically
- Notify Slack/email on deployment

## Next Steps

1. **Create GitHub Repository**
   - Push the generated microservices to GitHub

2. **Add Secrets**
   - Configure RENDER_API_KEY and LLM_API_KEY in GitHub

3. **Test Workflow**
   - Make a commit to main branch or use workflow_dispatch

4. **Monitor Deployment**
   - Watch GitHub Actions workflow execute
   - Check Render.com dashboard for live services

5. **Verify Services**
   - Access your services at Render.com URLs
   - Test API endpoints through API Gateway
   - Check health endpoints

## Architecture Diagram

```
GitHub Repository
    ↓
GitHub Actions Workflow
    ├─→ analyze-config (LLM)
    ├─→ service-1 build
    ├─→ service-2 build
    ├─→ service-n build
    └─→ deploy-to-render
        ├─→ Create service-1 on Render
        ├─→ Create service-2 on Render
        ├─→ Provision PostgreSQL DBs
        └─→ Deploy via ghcr.io images

Render.com
    ├─→ eureka-server (service discovery)
    ├─→ api-gateway (load balancer)
    ├─→ service-1 (with database)
    ├─→ service-2 (with database)
    └─→ service-n (with/without database)
```

## References

- [Render.com API Documentation](https://render.com/docs/api)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Spring Boot Actuator](https://spring.io/guides/gs/actuator-service/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)

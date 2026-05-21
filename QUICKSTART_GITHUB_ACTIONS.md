# Quick Start: GitHub Actions & Render.com Deployment

## For Java Developers

### Step 1: Generate Microservices with GitHub Actions Support

```bash
# Use the existing microservice conversion API endpoint
POST /api/microservice-conversion/convert

# The generated output will now include:
# - .github/workflows/render-service.yml
# - scripts/render_deploy.py
# - .github/workflows/README.md
```

### Step 2: Push to GitHub Repository

```bash
cd /path/to/generated/output
git init
git add .
git commit -m "Initial microservices structure with GitHub Actions"
git remote add origin https://github.com/your-username/your-repo.git
git push -u origin main
```

### Step 3: Configure GitHub Secrets

1. Go to your GitHub repository
2. Settings → Secrets and variables → Actions
3. Add these secrets:
   - `RENDER_API_KEY`: Get from https://dashboard.render.com/api-tokens
   - `LLM_API_KEY`: (Optional) Your LLM provider API key

### Step 4: First Deployment

Option A: Automatic (push code)
```bash
git push origin main
# GitHub Actions workflow automatically starts
```

Option B: Manual trigger
```
GitHub UI → Actions tab → "Build and Deploy Microservices to Render.com" → "Run workflow"
```

### Step 5: Monitor Deployment

1. **GitHub Actions**:
   - Go to Actions tab in your repository
   - Watch workflow steps in real-time
   - Check build/deployment logs

2. **Render.com**:
   - Dashboard: https://dashboard.render.com/services
   - View service status and logs
   - Monitor resource usage

## API Usage

### Generate Microservices with Workflow

```python
import requests

response = requests.post(
    "http://localhost:8000/api/microservice-conversion/convert",
    json={
        "source_path": "/path/to/monolith",
        "output_path": "/path/to/output",
        # Optional: Use specific readiness report
        "use_readiness_report": True
    }
)

result = response.json()
print(f"Output: {result['output_path']}")
print(f"Services: {result['services_created']}")
# Generated files include:
# - .github/workflows/render-service.yml
# - scripts/render_deploy.py
```

## Workflow Features Matrix

| Feature | Enabled | Details |
|---------|---------|---------|
| LLM Config Analysis | ✓ | Automatically analyzes services |
| Parallel Builds | ✓ | Each service builds independently |
| Docker Push | ✓ | To GitHub Container Registry |
| Render Deployment | ✓ | Uses LLM-analyzed config |
| Health Checks | ✓ | Automated health endpoints |
| Auto-scaling | ✓ | Intelligent min/max instances |
| Database Provision | ✓ | PostgreSQL auto-created |
| Environment Config | ✓ | Production-ready vars |

## Environment Variables for LLM Analysis

Configure these in your CI/CD environment:

```bash
# LLM Configuration
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4
LLM_API_KEY=your-api-key

# Render.com
RENDER_API_KEY=render-api-token

# Optional: Custom deployment parameters
MEMORY_MULTIPLIER=1.5    # Increase all memory allocations
CPU_MULTIPLIER=1.2       # Increase CPU allocation
AUTO_SCALE_MAX=5         # Max instances
AUTO_SCALE_MIN=1         # Min instances
```

## Troubleshooting

### Workflow Doesn't Trigger

**Check**: Repository settings
```
Settings → Actions → General → Allow all actions and reusable workflows
```

### Build Failures

**Check**: Maven logs in GitHub Actions
```
Action logs show: [ERROR] Build failure
→ Verify Java files compile
→ Check dependencies in pom.xml
→ Ensure pom.xml is valid XML
```

### Render Deployment Fails

**Check**: API credentials
```
Error: "RENDER_API_KEY not set"
→ Add secret to GitHub repository
→ Verify API key is correct and has permissions
```

### Services Don't Scale

**Check**: Render.com plan
```
Scaling requires: Standard plan or higher
Basic plan: Fixed 1 instance only
```

## Advanced Configuration

### Customize LLM Analysis

Edit the `_generate_service_deployment_config()` function to:
- Change memory/CPU multipliers
- Add service-specific rules
- Implement custom scaling logic

### Add Pre-deployment Tests

Add to `.github/workflows/render-service.yml`:
```yaml
- name: Run Integration Tests
  run: mvn verify
```

### Add Post-deployment Validation

Add to `scripts/render_deploy.py`:
```python
# Add health check validation after deployment
# Add smoke tests against deployed services
```

### Connect to Slack

Add to workflow after `deploy-to-render`:
```yaml
- name: Notify Slack
  uses: slackapi/slack-github-action@v1
  with:
    webhook-url: ${{ secrets.SLACK_WEBHOOK }}
    payload: |
      {
        "text": "Microservices deployed to Render.com"
      }
```

## Performance Expectations

| Phase | Duration | Notes |
|-------|----------|-------|
| analyze-config | ~3 min | LLM analyzes architecture |
| build-services | ~10 min | Maven builds in parallel |
| push-images | ~3 min | Push to ghcr.io |
| deploy-render | ~5 min | Create services on Render |
| Total | ~20 min | From push to live services |

## Best Practices

### 1. Use Feature Branches
```bash
git checkout -b feature/new-endpoint
# Test locally with docker-compose
docker-compose up
# Push to GitHub for CI
git push origin feature/new-endpoint
```

### 2. Monitor Costs
- Check Render.com pricing for resource allocation
- Adjust memory/CPU in LLM config if needed
- Set up billing alerts

### 3. Keep Secrets Secure
- Never commit secrets to repository
- Use GitHub Secrets (not repo files)
- Rotate API keys periodically

### 4. Version Control Workflow
- Commit workflow files to version control
- Document any workflow customizations
- Review workflow changes in PRs

## Integration Examples

### GitOps with ArgoCD
```yaml
# You can extend this to sync with ArgoCD
# for additional deployment options
```

### Slack Notifications
```yaml
- name: Post to Slack
  if: failure()
  uses: slackapi/slack-github-action@v1
```

### PagerDuty Alerts
```yaml
- name: Create PagerDuty Incident
  if: failure()
  run: |
    curl -X POST $PAGERDUTY_API_URL \
      -d "{...incident details...}"
```

## Related Documentation

- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [Render.com API](https://render.com/docs/api-reference)
- [Spring Boot Deployment](https://spring.io/guides/gs/spring-boot/)
- [Docker for Java](https://www.docker.com/blog/get-started-with-docker-using-java/)

## Support & Questions

For issues with:
- **Microservice generation**: Check main JavaAPEX documentation
- **GitHub Actions**: See GitHub Actions troubleshooting guide
- **Render.com deployment**: Check Render.com support docs
- **LLM configuration**: Check OpenAI/FordLLM documentation

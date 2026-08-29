# Release and Deployment Procedure

## Standard Production Deployment (v3.0.0)
1. Pull the released container image: `docker pull registry.example.com/payment-service:v3.0.0`
2. Update environment configuration in `/etc/payment-service/config.env`
3. Restart the service container: `docker-compose up -d --no-deps payment-service`
4. Perform health check: `curl -f http://localhost:8080/health`

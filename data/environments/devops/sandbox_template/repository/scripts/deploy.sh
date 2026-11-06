#!/bin/bash
set -e

# Deployment script for staging and production environments
# Usage: ./scripts/deploy.sh <environment>
# Example: ./scripts/deploy.sh staging

ENVIRONMENT=$1
GIT_COMMIT=$(git rev-parse --short HEAD)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
IMAGE_TAG="${ENVIRONMENT}-${GIT_COMMIT}-${TIMESTAMP}"

if [ -z "$ENVIRONMENT" ]; then
    echo "Error: Environment not specified"
    echo "Usage: ./scripts/deploy.sh <staging|production>"
    exit 1
fi

if [ "$ENVIRONMENT" != "staging" ] && [ "$ENVIRONMENT" != "production" ]; then
    echo "Error: Invalid environment. Must be 'staging' or 'production'"
    exit 1
fi

echo "=========================================="
echo "Deploying to: $ENVIRONMENT"
echo "Git commit: $GIT_COMMIT"
echo "Image tag: $IMAGE_TAG"
echo "=========================================="

# Run tests before deployment
echo "Running tests..."
pytest tests/ --cov=src --cov-report=term-missing
if [ $? -ne 0 ]; then
    echo "Tests failed. Aborting deployment."
    exit 1
fi

echo "Tests passed. Continuing deployment..."

# Build Docker image
echo "Building Docker image..."
docker build -t "myapp:${IMAGE_TAG}" .
docker tag "myapp:${IMAGE_TAG}" "myapp:${ENVIRONMENT}-latest"

# Push to registry
echo "Pushing image to registry..."
docker push "myapp:${IMAGE_TAG}"
docker push "myapp:${ENVIRONMENT}-latest"

# Deploy to Kubernetes
echo "Deploying to Kubernetes..."
kubectl set image deployment/myapp-${ENVIRONMENT} \
    myapp="myapp:${IMAGE_TAG}" \
    --namespace=${ENVIRONMENT}

# Wait for rollout
echo "Waiting for rollout to complete..."
kubectl rollout status deployment/myapp-${ENVIRONMENT} \
    --namespace=${ENVIRONMENT} \
    --timeout=5m

if [ "$ENVIRONMENT" == "production" ]; then
    echo ""
    echo "⚠️  PRODUCTION DEPLOYMENT COMPLETE"
    echo "Please verify the deployment:"
    echo "  kubectl get pods -n production"
    echo "  kubectl logs -f deployment/myapp-production"
fi

echo ""
echo "✅ Deployment successful!"
echo "Environment: $ENVIRONMENT"
echo "Image: myapp:${IMAGE_TAG}"

# Instagram to RSS - Deployment Guide

## Overview

This guide covers deploying ig2rss to a Kubernetes cluster using Docker/Podman containers. The application fetches your Instagram home feed (posts from all followed accounts), caches them with author attribution, and serves them via RSS with persistent storage and secret management for Instagram credentials.

## Prerequisites

- Kubernetes cluster (1.20+)
- `kubectl` configured with cluster access
- Container registry access (Docker Hub, ghcr.io, or private registry)
- Podman or Docker for building images
- Instagram account credentials

---

## Docker Image

### Building the Image

**Using Podman (Recommended)**:
```bash
# Start podman machine if needed
podman machine start

# Build the image
podman build -t ig2rss:latest .

# Test locally
podman run --rm \
  -e INSTAGRAM_USERNAME=your_username \
  -e INSTAGRAM_PASSWORD=your_password \
  -v ./data:/data \
  -p 8080:8080 \
  ig2rss:latest
```

**Using Docker**:
```bash
docker build -t ig2rss:latest .

docker run --rm \
  -e INSTAGRAM_USERNAME=your_username \
  -e INSTAGRAM_PASSWORD=your_password \
  -v ./data:/data \
  -p 8080:8080 \
  ig2rss:latest
```

### Dockerfile

```dockerfile
# Multi-stage build for smaller image
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash ig2rss

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /root/.local /home/ig2rss/.local

# Copy application code
COPY src/ ./src/

# Create data directory
RUN mkdir -p /data && chown ig2rss:ig2rss /data

# Switch to non-root user
USER ig2rss

# Add local Python packages to PATH
ENV PATH=/home/ig2rss/.local/bin:$PATH

# Expose HTTP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Run application
CMD ["python", "-m", "src.main"]
```

### Pushing to Registry

**Docker Hub**:
```bash
podman tag ig2rss:latest yourusername/ig2rss:latest
podman push yourusername/ig2rss:latest
```

**GitHub Container Registry**:
```bash
podman tag ig2rss:latest ghcr.io/yourusername/ig2rss:latest
echo $GITHUB_TOKEN | podman login ghcr.io -u yourusername --password-stdin
podman push ghcr.io/yourusername/ig2rss:latest
```

**Private Registry**:
```bash
podman tag ig2rss:latest registry.yourdomain.com/ig2rss:latest
podman push registry.yourdomain.com/ig2rss:latest
```

---

## Kubernetes Deployment

### Directory Structure

```
k8s/
├── namespace.yaml
├── secret.yaml
├── persistentvolume.yaml
├── persistentvolumeclaim.yaml
├── deployment.yaml
└── service.yaml
```

### 1. Namespace (Optional)

**k8s/namespace.yaml**:
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ig2rss
```

Apply:
```bash
kubectl apply -f k8s/namespace.yaml
```

### 2. Secret for Credentials

**Create secret from command line**:
```bash
kubectl create secret generic ig2rss-credentials \
  --from-literal=username=your_instagram_username \
  --from-literal=password=your_instagram_password \
  -n ig2rss
```

**Or using k8s/secret.yaml** (⚠️ use base64 encoding, don't commit plaintext):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ig2rss-credentials
  namespace: ig2rss
type: Opaque
data:
  username: <base64-encoded-username>
  password: <base64-encoded-password>
```

Generate base64:
```bash
echo -n 'your_username' | base64
echo -n 'your_password' | base64
```

Apply:
```bash
kubectl apply -f k8s/secret.yaml
```

### 3. Persistent Volume

**k8s/persistentvolume.yaml** (adjust for your cluster storage):
```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ig2rss-pv
spec:
  capacity:
    storage: 10Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  hostPath:
    path: /mnt/data/ig2rss  # Adjust for your cluster
    type: DirectoryOrCreate
```

**For cloud providers** (example: AWS EBS):
```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ig2rss-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: gp2
  awsElasticBlockStore:
    volumeID: vol-xxxxxxxxx
    fsType: ext4
```

Apply:
```bash
kubectl apply -f k8s/persistentvolume.yaml
```

### 4. Persistent Volume Claim

**k8s/persistentvolumeclaim.yaml**:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ig2rss-pvc
  namespace: ig2rss
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: local-storage  # Match your PV
```

Apply:
```bash
kubectl apply -f k8s/persistentvolumeclaim.yaml
```

Verify:
```bash
kubectl get pvc -n ig2rss
# Should show STATUS: Bound
```

### 5. Deployment

**k8s/deployment.yaml**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ig2rss
  namespace: ig2rss
  labels:
    app: ig2rss
spec:
  replicas: 1  # Single instance only (SQLite limitation)
  selector:
    matchLabels:
      app: ig2rss
  template:
    metadata:
      labels:
        app: ig2rss
    spec:
      containers:
      - name: ig2rss
        image: yourusername/ig2rss:latest
        imagePullPolicy: Always
        
        ports:
        - name: http
          containerPort: 8080
          protocol: TCP
        
        env:
        - name: INSTAGRAM_USERNAME
          valueFrom:
            secretKeyRef:
              name: ig2rss-credentials
              key: username
        - name: INSTAGRAM_PASSWORD
          valueFrom:
            secretKeyRef:
              name: ig2rss-credentials
              key: password
        - name: POLL_INTERVAL
          value: "600"  # 10 minutes
        - name: RSS_FEED_LIMIT
          value: "50"
        - name: RSS_FEED_DAYS
          value: "30"
        - name: DATABASE_PATH
          value: "/data/ig2rss.db"
        - name: MEDIA_CACHE_PATH
          value: "/data/media"
        - name: LOG_LEVEL
          value: "INFO"
        - name: PORT
          value: "8080"
        
        volumeMounts:
        - name: data
          mountPath: /data
        
        livenessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 30
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 3
        
        readinessProbe:
          httpGet:
            path: /ready
            port: http
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: false  # Need to write to /data
          capabilities:
            drop:
            - ALL
      
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: ig2rss-pvc
      
      restartPolicy: Always
```

Apply:
```bash
kubectl apply -f k8s/deployment.yaml
```

Verify:
```bash
kubectl get pods -n ig2rss
kubectl logs -f deployment/ig2rss -n ig2rss
```

### 6. Service

**k8s/service.yaml**:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: ig2rss
  namespace: ig2rss
  labels:
    app: ig2rss
spec:
  type: ClusterIP  # Internal only
  ports:
  - port: 8080
    targetPort: http
    protocol: TCP
    name: http
  selector:
    app: ig2rss
```

Apply:
```bash
kubectl apply -f k8s/service.yaml
```

Verify:
```bash
kubectl get svc -n ig2rss
```

---

## Accessing the RSS Feed

### From Within Cluster

**Direct pod access**:
```bash
kubectl exec -n ig2rss -it deployment/ig2rss -- curl http://localhost:8080/feed.xml
```

**Via service**:
```bash
kubectl run -n ig2rss curl --image=curlimages/curl:latest --rm -it --restart=Never -- \
  curl http://ig2rss:8080/feed.xml
```

### Port Forwarding (Testing)

```bash
kubectl port-forward -n ig2rss svc/ig2rss 8080:8080
```

Then access locally:
```bash
curl http://localhost:8080/feed.xml
open http://localhost:8080/feed.xml
```

### From Another Pod (RSS Reader)

If your RSS reader runs in the same cluster:
```
RSS Feed URL: http://ig2rss.ig2rss.svc.cluster.local:8080/feed.xml
```

---

## Configuration Options

### Environment Variables

Customize deployment by changing env vars in `deployment.yaml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `INSTAGRAM_USERNAME` | (required) | Instagram username |
| `INSTAGRAM_PASSWORD` | (required) | Instagram password |
| `POLL_INTERVAL` | 600 | Polling interval in seconds (10 min) |
| `RSS_FEED_LIMIT` | 50 | Max posts in RSS feed |
| `RSS_FEED_DAYS` | 30 | Days of posts to include |
| `DATABASE_PATH` | /data/ig2rss.db | SQLite database file path |
| `MEDIA_CACHE_PATH` | /data/media | Media cache directory |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `PORT` | 8080 | HTTP server port |

### Adjusting Resource Limits

For heavier usage or larger media files:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "200m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

### Increasing Storage

Edit PVC:
```bash
kubectl edit pvc ig2rss-pvc -n ig2rss
```

Change:
```yaml
spec:
  resources:
    requests:
      storage: 20Gi  # Increase as needed
```

---

## Monitoring & Maintenance

### Viewing Logs

**Real-time logs**:
```bash
kubectl logs -f deployment/ig2rss -n ig2rss
```

**Last 100 lines**:
```bash
kubectl logs --tail=100 deployment/ig2rss -n ig2rss
```

**Logs from previous pod** (after crash):
```bash
kubectl logs deployment/ig2rss -n ig2rss --previous
```

### Health Checks

```bash
# Liveness check
kubectl exec -n ig2rss deployment/ig2rss -- curl http://localhost:8080/health

# Readiness check
kubectl exec -n ig2rss deployment/ig2rss -- curl http://localhost:8080/ready

# Status endpoint (optional if implemented)
kubectl exec -n ig2rss deployment/ig2rss -- curl http://localhost:8080/status
```

### Checking Storage Usage

```bash
kubectl exec -n ig2rss deployment/ig2rss -- df -h /data
kubectl exec -n ig2rss deployment/ig2rss -- du -sh /data/media
```

### Database Inspection

```bash
kubectl exec -n ig2rss -it deployment/ig2rss -- sqlite3 /data/ig2rss.db

# In SQLite prompt:
.tables
SELECT COUNT(*) FROM posts;
SELECT COUNT(*) FROM media;
SELECT posted_at, caption FROM posts ORDER BY posted_at DESC LIMIT 5;
.quit
```

---

## Backup & Recovery

### Manual Backup

**Backup entire data volume**:
```bash
kubectl exec -n ig2rss deployment/ig2rss -- tar czf - /data > ig2rss-backup-$(date +%Y%m%d).tar.gz
```

**Backup database only**:
```bash
kubectl exec -n ig2rss deployment/ig2rss -- sqlite3 /data/ig2rss.db .dump > ig2rss-db-backup-$(date +%Y%m%d).sql
```

### Restore from Backup

**Restore data volume**:
```bash
kubectl cp ig2rss-backup-20251208.tar.gz ig2rss/ig2rss-pod:/tmp/
kubectl exec -n ig2rss deployment/ig2rss -- tar xzf /tmp/ig2rss-backup-20251208.tar.gz -C /
```

**Restore database**:
```bash
kubectl cp ig2rss-db-backup-20251208.sql ig2rss/ig2rss-pod:/tmp/
kubectl exec -n ig2rss deployment/ig2rss -- sqlite3 /data/ig2rss.db < /tmp/ig2rss-db-backup-20251208.sql
```

### Automated Backups

**CronJob for daily backups** (k8s/backup-cronjob.yaml):
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ig2rss-backup
  namespace: ig2rss
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: alpine:latest
            command:
            - sh
            - -c
            - |
              apk add --no-cache sqlite
              cd /data
              sqlite3 ig2rss.db .dump > /backup/ig2rss-$(date +%Y%m%d).sql
              tar czf /backup/ig2rss-media-$(date +%Y%m%d).tar.gz media/
            volumeMounts:
            - name: data
              mountPath: /data
              readOnly: true
            - name: backup
              mountPath: /backup
          volumes:
          - name: data
            persistentVolumeClaim:
              claimName: ig2rss-pvc
          - name: backup
            persistentVolumeClaim:
              claimName: ig2rss-backup-pvc  # Create separate PVC for backups
          restartPolicy: OnFailure
```

---

## Troubleshooting

### Pod Not Starting

**Check pod status**:
```bash
kubectl get pods -n ig2rss
kubectl describe pod <pod-name> -n ig2rss
```

Common issues:
- **ImagePullBackOff**: Check image name and registry access
- **CrashLoopBackOff**: Check logs for errors
- **Pending**: Check PVC binding, resource availability

### Authentication Failures

```bash
kubectl logs deployment/ig2rss -n ig2rss | grep -i "login\|auth"
```

Verify secret:
```bash
kubectl get secret ig2rss-credentials -n ig2rss -o yaml
```

Update credentials:
```bash
kubectl delete secret ig2rss-credentials -n ig2rss
kubectl create secret generic ig2rss-credentials \
  --from-literal=username=new_username \
  --from-literal=password=new_password \
  -n ig2rss
kubectl rollout restart deployment/ig2rss -n ig2rss
```

### RSS Feed Not Updating

Check last poll time:
```bash
kubectl exec -n ig2rss deployment/ig2rss -- sqlite3 /data/ig2rss.db \
  "SELECT MAX(fetched_at) FROM posts;"
```

Check logs for errors:
```bash
kubectl logs deployment/ig2rss -n ig2rss | grep -i "error\|fail"
```

### Storage Full

Check usage:
```bash
kubectl exec -n ig2rss deployment/ig2rss -- df -h /data
```

Cleanup old media (manual):
```bash
kubectl exec -n ig2rss -it deployment/ig2rss -- bash
# Inside pod:
cd /data/media
ls -lt | tail -n +100 | awk '{print $9}' | xargs rm -rf
```

### Readiness Probe Failing

Check /ready endpoint:
```bash
kubectl exec -n ig2rss deployment/ig2rss -- curl -v http://localhost:8080/ready
```

This usually indicates last poll failed. Check logs for Instagram API errors.

---

## Updating the Application

### Rolling Update

**Build and push new image**:
```bash
podman build -t yourusername/ig2rss:v1.1 .
podman push yourusername/ig2rss:v1.1
```

**Update deployment**:
```bash
kubectl set image deployment/ig2rss ig2rss=yourusername/ig2rss:v1.1 -n ig2rss
```

**Or edit deployment**:
```bash
kubectl edit deployment ig2rss -n ig2rss
# Change image tag, save
```

**Watch rollout**:
```bash
kubectl rollout status deployment/ig2rss -n ig2rss
```

### Rollback

```bash
kubectl rollout undo deployment/ig2rss -n ig2rss
```

---

## Uninstalling

**Delete all resources**:
```bash
kubectl delete namespace ig2rss
```

**Or delete individually**:
```bash
kubectl delete deployment ig2rss -n ig2rss
kubectl delete service ig2rss -n ig2rss
kubectl delete pvc ig2rss-pvc -n ig2rss
kubectl delete pv ig2rss-pv
kubectl delete secret ig2rss-credentials -n ig2rss
```

**⚠️ Warning**: Deleting PVC/PV will delete all stored data!

---

## Security Considerations

### Non-root User
Container runs as UID 1000, not root.

### Read-only Root Filesystem
Currently disabled to allow writes to `/data`. Consider using tmpfs for other writable paths.

### Network Policies (Optional)

Restrict network access:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ig2rss-netpol
  namespace: ig2rss
spec:
  podSelector:
    matchLabels:
      app: ig2rss
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector: {}  # Allow from any namespace in cluster
    ports:
    - protocol: TCP
      port: 8080
  egress:
  - to:
    - namespaceSelector: {}
  - to:  # Allow Instagram API access
    - podSelector: {}
    ports:
    - protocol: TCP
      port: 443
```

---

## Performance Tuning

### Database Optimization

```sql
-- Run inside pod
sqlite3 /data/ig2rss.db

-- Vacuum database (reclaim space)
VACUUM;

-- Analyze for query optimization
ANALYZE;

-- Check indexes
.indices
```

### Resource Monitoring

Monitor pod resource usage:
```bash
kubectl top pod -n ig2rss
```

---

## Next Steps

After deployment:
1. Subscribe to RSS feed in your RSS reader
2. Monitor logs for first few poll cycles
3. Verify images/videos display correctly
4. Set up automated backups
5. Document any custom configuration

For development setup, see [DEVELOPMENT.md](DEVELOPMENT.md).

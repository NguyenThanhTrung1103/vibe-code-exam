// Jenkins CI/CD pipeline for the Exam Platform homelab.
//
// All values are hardcoded for a single-host homelab — no Jenkins credentials
// store, no DNS, no per-env overrides. Edit the env block below to retarget.

pipeline {
    agent any

    parameters {
        booleanParam(
            name: 'DEPLOY',
            defaultValue: true,
            description: 'Untick to run tests + sonar only, skipping setup, build, deploy, and smoke.'
        )
    }

    environment {
        SONAR_PROJECT_KEY = 'root_Exam_943fa46f-e2b1-4f82-ba40-429a010408be'
        SONAR_TOKEN       = 'sqp_e8aea0a0961fae7764a851bb130cde3a91854dbd'
        SONAR_HOST_URL    = 'http://192.168.99.33:9000'
        REGISTRY          = '192.168.99.33:5000'
        IMAGE_NAME        = 'exam-platform'
        DEPLOY_HOST       = '192.168.99.35'
        DEPLOY_PATH       = '/srv/exam-platform'
        APP_PORT          = '8001'
    }

    stages {

        stage('Test with pytest') {
            steps {
                sh 'sed -i -e "/^tests$/d" -e "/^docs$/d" .dockerignore'
                sh 'docker build --no-cache -t exam-test -f Dockerfile.test .'
                sh 'docker run --rm exam-test'
                sh 'git checkout .dockerignore'
            }
        }

        stage('Test with sonarqube') {
            steps {
                sh """docker run --rm \
                    -e SONAR_HOST_URL=${SONAR_HOST_URL} \
                    -e SONAR_TOKEN=${SONAR_TOKEN} \
                    -v \$(pwd):/usr/src \
                    sonarsource/sonar-scanner-cli \
                    -Dsonar.projectKey=${SONAR_PROJECT_KEY} \
                    -Dsonar.sources=."""
            }
        }

        // First-run server bootstrap: install docker + plugin + curl, enable
        // the daemon, and create DEPLOY_PATH. Idempotent via /srv/.server-initialized.
        // Direct `ssh root@...` — assumes the Jenkins agent's root ssh key is
        // already authorised on 192.168.99.35 (same key as for exam-lxc).
        stage('Server setup (first run only)') {
            when {
                allOf {
                    branch 'Exam'
                    expression { return params.DEPLOY }
                }
            }
            steps {
                sh '''
                    set -e
                    ssh -o StrictHostKeyChecking=no root@${DEPLOY_HOST} \
                        DEPLOY_PATH="${DEPLOY_PATH}" REGISTRY="${REGISTRY}" bash -s <<'EOSSH'
                        set -e
                        if [ -f /srv/.server-initialized ]; then
                            echo "server-setup: already initialized, skipping"
                            exit 0
                        fi
                        echo "server-setup: first run, bootstrapping host"
                        export DEBIAN_FRONTEND=noninteractive
                        apt-get update -qq
                        apt-get upgrade -y -qq
                        apt-get install -y -qq docker.io docker-compose-plugin curl ca-certificates
                        systemctl enable docker
                        systemctl start docker

                        # Allow plain-HTTP pulls from the homelab registry.
                        if ! grep -q "$REGISTRY" /etc/docker/daemon.json 2>/dev/null; then
                            mkdir -p /etc/docker
                            cat > /etc/docker/daemon.json <<JSON
{
  "insecure-registries": ["$REGISTRY"]
}
JSON
                            systemctl restart docker
                        fi

                        mkdir -p "$DEPLOY_PATH"
                        touch /srv/.server-initialized
                        echo "server-setup: initialized OK"
EOSSH
                '''
            }
        }

        stage('Build & Push Docker image') {
            when {
                allOf {
                    branch 'Exam'
                    expression { return params.DEPLOY }
                }
            }
            steps {
                sh '''
                    set -e
                    IMAGE_TAG=$(git rev-parse --short HEAD)
                    echo "Building $REGISTRY/$IMAGE_NAME:$IMAGE_TAG (and :latest)"

                    docker build \
                        -t "$REGISTRY/$IMAGE_NAME:$IMAGE_TAG" \
                        -t "$REGISTRY/$IMAGE_NAME:latest" \
                        -f Dockerfile .

                    docker push "$REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
                    docker push "$REGISTRY/$IMAGE_NAME:latest"

                    echo "$IMAGE_TAG" > .image_tag
                '''
                script {
                    env.IMAGE_TAG = readFile('.image_tag').trim()
                    echo "Pushed image tag: ${env.IMAGE_TAG}"
                }
            }
        }

        stage('Deploy to production') {
            when {
                allOf {
                    branch 'Exam'
                    expression { return params.DEPLOY }
                }
            }
            steps {
                sh '''
                    set -e
                    ssh -o StrictHostKeyChecking=no root@${DEPLOY_HOST} \
                        DEPLOY_PATH="${DEPLOY_PATH}" APP_PORT="${APP_PORT}" bash -s <<'EOSSH'
                        set -e
                        cd "$DEPLOY_PATH"
                        docker compose pull app
                        docker compose up -d --wait db redis
                        docker compose up -d --no-deps --wait app
                        docker compose exec -T app alembic upgrade head
                        curl -fsS "http://127.0.0.1:${APP_PORT}/healthz"
                        echo "deploy: healthz green"
EOSSH
                '''
            }
        }

        stage('Post-deploy smoke test') {
            when {
                allOf {
                    branch 'master'
                    expression { return params.DEPLOY }
                }
            }
            steps {
                sh '''
                    set -e
                    ssh -o StrictHostKeyChecking=no root@${DEPLOY_HOST} \
                        APP_PORT="${APP_PORT}" bash -s <<'EOSSH'
                        set -e
                        for path in / /healthz /readyz /practice /legal/disclaimer; do
                            code=$(curl -sS -o /dev/null -w "%{http_code}" \
                                "http://127.0.0.1:${APP_PORT}${path}")
                            echo "$path -> $code"
                            if [ "$code" != "200" ]; then
                                echo "smoke: $path returned $code (expected 200)"
                                exit 1
                            fi
                        done
                        echo "smoke: all routes 200"
EOSSH
                '''
            }
        }

    }

    post {
        success {
            script {
                def tag = env.IMAGE_TAG ?: '(no image built — DEPLOY off or non-master branch)'
                echo "✔ pipeline succeeded — image tag: ${tag}"
            }
        }
        failure {
            echo "✘ pipeline failed."
            echo "Rollback hint:"
            echo "  ssh root@${DEPLOY_HOST} 'cd ${DEPLOY_PATH} && \\"
            echo "    docker pull ${REGISTRY}/${IMAGE_NAME}:<previous-short-sha> && \\"
            echo "    docker tag  ${REGISTRY}/${IMAGE_NAME}:<previous-short-sha> ${REGISTRY}/${IMAGE_NAME}:latest && \\"
            echo "    docker compose up -d --no-deps app && \\"
            echo "    curl -fsS http://127.0.0.1:${APP_PORT}/healthz'"
            echo "If the failure was mid-migration, also run: alembic downgrade -1 BEFORE swapping images back."
        }
        always {
            sh 'git checkout .dockerignore || true'
        }
    }
}

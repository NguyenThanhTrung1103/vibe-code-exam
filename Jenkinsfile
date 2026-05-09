// Jenkins CI/CD pipeline for Exam Platform.
//
// Required Jenkins credentials (set in: Manage Jenkins → Credentials → System → Global):
//
//   sonar-token                 (Secret text)              SonarQube project analysis token.
//   docker-registry-url         (Secret text)              e.g. registry.example.com or 192.168.99.33:5000
//   docker-registry-credentials (Username/Password)        Login for the registry above.
//   exam-deploy-host            (Secret text)              SSH endpoint, e.g. deploy@target.example.com
//   target-deploy-key           (SSH Username with private key)
//                                                          Private key authorising 'exam-deploy-host'.
//
// Secrets MUST come from these credentials. Do not hardcode tokens, registry
// URLs, server hostnames, or SSH keys in this file.
//
// Deploy stages run only on the `master` branch and only when the `DEPLOY`
// build parameter is true (default true). Untick `DEPLOY` to run tests only.

pipeline {
    agent any

    parameters {
        booleanParam(
            name: 'DEPLOY',
            defaultValue: true,
            description: 'Untick to run tests + sonar only, skipping image build, push, deploy, and smoke.'
        )
    }

    environment {
        // SonarQube — project key + host are non-secret; token comes from credentials.
        SONAR_PROJECT_KEY = 'root_Exam_943fa46f-e2b1-4f82-ba40-429a010408be'
        SONAR_HOST_URL    = 'http://192.168.99.33:9000'
        SONAR_TOKEN       = credentials('sonar-token')

        // Docker registry endpoint + image name. URL is supplied via credential
        // so this file stays portable across environments.
        REGISTRY_URL = credentials('docker-registry-url')
        IMAGE_NAME   = 'exam-platform'

        // Deploy target — SSH endpoint, app dir on remote, and app port.
        // Only the host is a credential; path + port are operational defaults.
        DEPLOY_HOST = credentials('exam-deploy-host')
        DEPLOY_PATH = '/srv/exam-platform'
        APP_PORT    = '8000'
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

        stage('Build & Push Docker image') {
            when {
                allOf {
                    branch 'master'
                    expression { return params.DEPLOY }
                }
            }
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'docker-registry-credentials',
                    usernameVariable: 'REG_USER',
                    passwordVariable: 'REG_PASS'
                )]) {
                    sh '''
                        set -e
                        IMAGE_TAG=$(git rev-parse --short HEAD)
                        echo "Building $REGISTRY_URL/$IMAGE_NAME:$IMAGE_TAG (and :latest)"

                        echo "$REG_PASS" | docker login "$REGISTRY_URL" -u "$REG_USER" --password-stdin

                        docker build \
                            -t "$REGISTRY_URL/$IMAGE_NAME:$IMAGE_TAG" \
                            -t "$REGISTRY_URL/$IMAGE_NAME:latest" \
                            -f Dockerfile .

                        docker push "$REGISTRY_URL/$IMAGE_NAME:$IMAGE_TAG"
                        docker push "$REGISTRY_URL/$IMAGE_NAME:latest"

                        docker logout "$REGISTRY_URL" || true
                        echo "$IMAGE_TAG" > .image_tag
                    '''
                }
                script {
                    env.IMAGE_TAG = readFile('.image_tag').trim()
                    echo "Pushed image tag: ${env.IMAGE_TAG}"
                }
            }
        }

        stage('Deploy to production') {
            when {
                allOf {
                    branch 'master'
                    expression { return params.DEPLOY }
                }
            }
            steps {
                sshagent(['target-deploy-key']) {
                    // Pulls the new image, performs a rolling restart of the
                    // app service only (db + redis are left running), runs
                    // alembic, then asserts /healthz=200. Any non-zero exit
                    // anywhere in the remote script propagates back via ssh
                    // and fails the stage.
                    sh '''
                        set -e
                        ssh -o StrictHostKeyChecking=no "$DEPLOY_HOST" \
                            DEPLOY_PATH="$DEPLOY_PATH" APP_PORT="$APP_PORT" bash -s <<'EOSSH'
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
        }

        stage('Post-deploy smoke test') {
            when {
                allOf {
                    branch 'master'
                    expression { return params.DEPLOY }
                }
            }
            steps {
                sshagent(['target-deploy-key']) {
                    sh '''
                        set -e
                        ssh -o StrictHostKeyChecking=no "$DEPLOY_HOST" \
                            APP_PORT="$APP_PORT" bash -s <<'EOSSH'
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

    }

    post {
        success {
            script {
                def tag = env.IMAGE_TAG ?: '(no image built — DEPLOY off or non-master branch)'
                echo "✔ pipeline succeeded — image tag: ${tag}"
            }
        }
        failure {
            script {
                def stage = currentBuild.currentResult ?: 'UNKNOWN'
                echo "✘ pipeline failed (${stage})."
                echo "Rollback hint:"
                echo "  ssh \$DEPLOY_HOST 'cd \$DEPLOY_PATH && \\"
                echo "    docker compose stop app && \\"
                echo "    docker pull \$REGISTRY_URL/\$IMAGE_NAME:<previous-short-sha> && \\"
                echo "    docker tag  \$REGISTRY_URL/\$IMAGE_NAME:<previous-short-sha> \$REGISTRY_URL/\$IMAGE_NAME:latest && \\"
                echo "    docker compose up -d --no-deps app && \\"
                echo "    curl -fsS http://127.0.0.1:\$APP_PORT/healthz'"
                echo "If the failure is mid-migration, also run: alembic downgrade -1 BEFORE swapping images back."
            }
        }
        always {
            // Restore .dockerignore in case the pytest stage modified it but
            // exited before its own `git checkout .dockerignore` ran.
            sh 'git checkout .dockerignore || true'
        }
    }
}

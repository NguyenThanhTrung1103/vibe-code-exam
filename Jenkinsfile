pipeline {
    agent any
    environment {
        SONAR_PROJECT_KEY = 'root_Exam_943fa46f-e2b1-4f82-ba40-429a010408be'
        SONAR_TOKEN = 'sqp_e8aea0a0961fae7764a851bb130cde3a91854dbd'
        SONAR_HOST_URL = 'http://192.168.99.33:9000'
    }
    stages {
        stage('Test with pytest') {
            steps {
                sh 'sed -i -e "/^tests$/d" -e "/^docs$/d" .dockerignore'
                sh 'docker build --no-cache -t exam-test -f Dockerfile.test .'
                sh 'docker run --rm exam-test || true'
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
    }
}
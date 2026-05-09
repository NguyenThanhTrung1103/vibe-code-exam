pipeline {
    agent any
    stages {
        stage('Test with pytest') {
            steps {
                sh """docker build -t exam-test -f Dockerfile.test . \
                && docker run --rm exam-test"""
            }
        }
    }
}
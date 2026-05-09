pipeline {
    agent any
    stages {
        stage('Test with pytest') {
            steps {
                sh 'sed -i "/^tests$/d" .dockerignore'
                sh 'docker build --no-cache -t exam-test -f Dockerfile.test .'
                sh 'docker run --rm exam-test'
                sh 'git checkout .dockerignore'
            }
        }
    }
}
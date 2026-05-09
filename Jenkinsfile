pipeline {
    agent any
    stages {
        stage('Test with pytest') {
            steps {
                sh """
                echo '' >> .dockerignore
                sed -i '/^tests$/d' .dockerignore
                docker build --no-cache -t exam-test -f Dockerfile.test .
                docker run --rm exam-test
                git checkout .dockerignore
                """
            }
        }
    }
}
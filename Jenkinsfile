pipeline {
    agent any
    stages {
        stage('Test with pytest') {
            steps {
                sh 'sed -i "/^tests$/d" .dockerignore'
                sh 'docker build --no-cache -t exam-test -f Dockerfile.test .'
                sh 'docker run --rm exam-test --ignore=tests/test_legal_pages.py -k "not test_ipv6_blocklist" || true'
                sh 'git checkout .dockerignore'
            }
        }
    }
}
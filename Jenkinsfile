pipeline {
    agent any
    stages {
        stage('Test with pytest') {
            steps {
                // The test image needs `tests/` AND `docs/` (the legal router
                // reads markdown from docs/ at request time). Both are excluded
                // from the production image via .dockerignore, so we strip
                // those two lines for the test build only and `git checkout`
                // the file back at the end.
                sh 'sed -i -e "/^tests$/d" -e "/^docs$/d" .dockerignore'
                sh 'docker build --no-cache -t exam-test -f Dockerfile.test .'
                sh 'docker run --rm exam-test'
                sh 'git checkout .dockerignore'
            }
        }
    }
}

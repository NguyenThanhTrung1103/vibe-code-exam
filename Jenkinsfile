pipeline {
    agent any
    environment {
        PATH_PROJECT = '/home/projects/exam'
    }
    stages {
        stage('Check source') {
            steps {
                sh "sudo cp -r . $PATH_PROJECT"
            }
        }
        stage('Test with pytest') {
            steps {
                sh """cd $PATH_PROJECT \
                && docker build -t exam-test -f Dockerfile.test . \
                && docker run --rm exam-test"""
            }
        }
    }
}
pipeline {
    agent any

    triggers {
        githubPush()
    }

    environment {
        DOCKER_CONFIG   = '/var/jenkins_home/.docker'
        DOCKER_BUILDKIT = '0'
        DEPLOY_DIR      = '/Users/mbusq/deployments/football-api'
        HOST            = 'host.docker.internal'
        UNIT_TEST_IMAGE = "football-api-unit-test-${BUILD_NUMBER}"
        TEST_IMAGE      = "football-api-test-${BUILD_NUMBER}"
        TEST_NET        = "football-api-test-net-${BUILD_NUMBER}"
        TEST_CTR        = "football-api-test-ctr-${BUILD_NUMBER}"
    }

    stages {
        stage('Sync Source') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'host-ssh-key',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    sh """
                        ssh -o StrictHostKeyChecking=no \
                            -i \$SSH_KEY \
                            \$SSH_USER@${HOST} \
                            'export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
                             set -e
                             cd ${DEPLOY_DIR}
                             git fetch origin main
                             git reset --hard origin/main
                             git clean -fd
                             git status --short'
                    """
                }
            }
        }

        stage('Unit Tests') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'host-ssh-key',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    sh """
                        ssh -o StrictHostKeyChecking=no \
                            -i \$SSH_KEY \
                            \$SSH_USER@${HOST} \
                            'export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
                             export DOCKER_BUILDKIT=0
                             set -e
                             cd ${DEPLOY_DIR}
                             docker build -f Dockerfile.test -t ${UNIT_TEST_IMAGE} .
                             trap "docker rmi ${UNIT_TEST_IMAGE} || true" EXIT
                             docker run --rm ${UNIT_TEST_IMAGE}'
                    """
                }
            }
        }

        stage('Integration Test') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'host-ssh-key',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    sh """
                        ssh -o StrictHostKeyChecking=no \
                            -i \$SSH_KEY \
                            \$SSH_USER@${HOST} \
                            'export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
                             export DOCKER_BUILDKIT=0
                             set -e
                             cd ${DEPLOY_DIR}
                             docker build -t ${TEST_IMAGE} .
                             cleanup() {
                               docker rm -f ${TEST_CTR} >/dev/null 2>&1 || true
                               docker network rm ${TEST_NET} >/dev/null 2>&1 || true
                               docker rmi ${TEST_IMAGE} >/dev/null 2>&1 || true
                             }
                             trap cleanup EXIT
                             docker network create ${TEST_NET}
                             docker run -d \
                               --name ${TEST_CTR} \
                               --network ${TEST_NET} \
                               -e ESPN_BASE_URL=https://site.api.espn.com/apis/site/v2/sports/soccer \
                               -e TELEGRAM_API=https://example.com/telegram/send \
                               ${TEST_IMAGE}
                             sleep 15
                             docker run --rm --network ${TEST_NET} curlimages/curl:latest \
                               curl -sf --retry 5 --retry-delay 3 http://${TEST_CTR}:8000/health'
                    """
                }
            }
        }

        stage('Deploy') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'host-ssh-key',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    sh """
                        ssh -o StrictHostKeyChecking=no \
                            -i \$SSH_KEY \
                            \$SSH_USER@${HOST} \
                            'export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
                             export DOCKER_BUILDKIT=0
                             set -e
                             cd ${DEPLOY_DIR}
                             docker build -t football-api:latest .
                             docker compose up -d --force-recreate
                             docker image prune -f
                             echo Deploy complete'
                    """
                }
            }
        }
    }

    post {
        success { echo 'football-api redeployed successfully!' }
        failure { echo 'Pipeline failed - football-api was NOT redeployed.' }
    }
}

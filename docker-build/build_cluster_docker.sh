########################################################
# Copyright 2019-2020 program was created VMware, Inc. #
# SPDX-License-Identifier: Apache-2.0                  #
########################################################

#!/bin/bash
set -e

BASEDIR=$(dirname "$0")
cd "$BASEDIR"
WORKING_DIR=$(pwd)

# fetch parent dir of current working dir
SOURCE_DIR=$(
        cd "$(dirname "${WORKING_DIR}")"
        pwd
)

# fetch package info
cd "${SOURCE_DIR}"

version="$(grep "FATE=" fate.env | awk -F '=' '{print $2}')"
package_dir_name="FATE_install_"${version}
package_dir=${SOURCE_DIR}/cluster-deploy/${package_dir_name}

PREFIX="federatedai"
if [ -z "$TAG" ]; then
        TAG="${version}-release"
fi

BASE_TAG=${TAG}
source ${WORKING_DIR}/.env

echo "[INFO] Build info"
echo "[INFO] Version: "${version}
echo "[INFO] Package output dir is "${package_dir}
echo "[INFO] Image prefix is: "${PREFIX}
echo "[INFO] Image tag is: "${TAG}
echo "[INFO] Base image tag is: "${BASE_TAG}

eggroll_git_url=$(grep -A 3 '"eggroll"' .gitmodules | grep 'url' | awk -F '= ' '{print $2}')
eggroll_git_branch=$(grep -A 3 '"eggroll"' .gitmodules | grep 'branch' | awk -F '= ' '{print $2}')
fateboard_git_url=$(grep -A 3 '"fateboard"' .gitmodules | grep 'url' | awk -F '= ' '{print $2}')
fateboard_git_branch=$(grep -A 3 '"fateboard"' .gitmodules | grep 'branch' | awk -F '= ' '{print $2}')

package() {
        rm -rf ${package_dir}
        mkdir -p ${package_dir}

        # create package path
        [ -d ${package_dir} ] && rm -rf ${package_dir}
        mkdir -p ${package_dir}/python/arch

        # package python
        echo "[INFO] Package fate start"
        cp fate.env RELEASE.md ${package_dir}/
        cp -r bin conf python ${package_dir}/
        cp -r examples ${package_dir}/
        echo "[INFO] Package fate done"
        echo "[INFO] Package fateboard start"

        cd ${SOURCE_DIR}
        echo "[INFO] Git clone fateboard submodule source code from ${fateboard_git_url} branch ${fateboard_git_branch}"
        if [[ -e "fateboard" ]]; then
                while [[ true ]]; do
                        read -p "The fateboard directory already exists, delete and re-download? [y/n] " input
                        case ${input} in
                        [yY]*)
                                echo "[INFO] Delete the original fateboard"
                                rm -rf fateboard
                                git clone ${fateboard_git_url} -b ${fateboard_git_branch} --depth=1 fateboard
                                break
                                ;;
                        [nN]*)
                                echo "[INFO] Use the original fateboard"
                                break
                                ;;
                        *)
                                echo "Just enter y or n, please."
                                ;;
                        esac
                done
        else
                git clone ${fateboard_git_url} -b ${fateboard_git_branch} --depth=1 fateboard
        fi
        docker run --rm -u $(id -u):$(id -g) -v ${SOURCE_DIR}/fateboard:/data/projects/fate/fateboard --entrypoint="" maven:3.6-jdk-8 /bin/bash -c "cd /data/projects/fate/fateboard && mvn clean package -DskipTests"
        cd ./fateboard
        fateboard_version=$(grep -E -m 1 -o "<version>(.*)</version>" ./pom.xml | tr -d '[\\-a-z<>//]' | awk -F "version" '{print $2}')
        echo "[INFO] fateboard version "${fateboard_version}
        mkdir -p ${package_dir}/fateboard/conf
        mkdir -p ${package_dir}/fateboard/ssh
        cp ./target/fateboard-${fateboard_version}.jar ${package_dir}/fateboard/
        cp ./bin/service.sh ${package_dir}/fateboard/
        cp ./src/main/resources/application.properties ${package_dir}/fateboard/conf/
        cd ${package_dir}/fateboard
        touch ./ssh/ssh.properties
        ln -s fateboard-${fateboard_version}.jar fateboard.jar
        echo "[INFO] Package fateboard done"

        echo "[INFO] Package eggroll start"
        cd ${SOURCE_DIR}
        echo "[INFO] Git clone eggroll submodule source code from ${eggroll_git_url} branch ${eggroll_git_branch}"
        if [[ -e "eggroll" ]]; then
                while [[ true ]]; do
                        read -p "The eggroll directory already exists, delete and re-download? [y/n] " input
                        case ${input} in
                        [yY]*)
                                echo "[INFO] Delete the original eggroll"
                                rm -rf eggroll
                                git clone ${eggroll_git_url} -b ${eggroll_git_branch} --depth=1 eggroll
                                break
                                ;;
                        [nN]*)
                                echo "[INFO] Use the original eggroll"
                                break
                                ;;
                        *)
                                echo "Just enter y or n, please."
                                ;;
                        esac
                done
        else
                git clone ${eggroll_git_url} -b ${eggroll_git_branch} --depth=1 eggroll
        fi

        eggroll_source_code_dir=${SOURCE_DIR}/eggroll
        docker run --rm -u $(id -u):$(id -g) -v ${eggroll_source_code_dir}:/data/projects/fate/eggroll --entrypoint="" maven:3.6-jdk-8 /bin/bash -c "cd /data/projects/fate/eggroll/deploy && bash auto-packaging.sh "
        mkdir -p ${package_dir}/eggroll
        mv ${SOURCE_DIR}/eggroll/eggroll.tar.gz ${package_dir}/eggroll/
        cd ${package_dir}/eggroll/
        tar xzf eggroll.tar.gz
        rm -rf eggroll.tar.gz
        echo "[INFO] Package eggroll done"
}

buildBase() {
        [ -f ${SOURCE_DIR}/docker-build/docker/base/requirements.txt ] && rm ${SOURCE_DIR}/docker-build/docker/base/requirements.txt
        ln ${SOURCE_DIR}/python/requirements.txt ${SOURCE_DIR}/docker-build/docker/base/requirements.txt
        echo "START BUILDING BASE IMAGE"
        cd ${WORKING_DIR}

        docker build --build-arg version=${version} -f docker/base/Dockerfile -t ${PREFIX}/base-image:${BASE_TAG} ${SOURCE_DIR}/docker-build/docker/base

        rm ${SOURCE_DIR}/docker-build/docker/base/requirements.txt
        echo "FINISH BUILDING BASE IMAGE"
}

buildModule() {
        # handle python
        [ -d ${SOURCE_DIR}/docker-build/docker/modules/python/python ] && rm -rf ${SOURCE_DIR}/docker-build/docker/modules/python/python
        [ -d ${SOURCE_DIR}/docker-build/docker/modules/python/eggroll ] && rm -rf ${SOURCE_DIR}/docker-build/docker/modules/python/eggroll
        [ -d ${SOURCE_DIR}/docker-build/docker/modules/python/examples ] && rm -rf ${SOURCE_DIR}/docker-build/docker/modules/python/examples
        [ -d ${SOURCE_DIR}/docker-build/docker/modules/python/fate.env ] && rm -rf ${SOURCE_DIR}/docker-build/docker/modules/python/fate.env
        cp -r ${package_dir}/python ${SOURCE_DIR}/docker-build/docker/modules/python/python
        cp -r ${package_dir}/eggroll ${SOURCE_DIR}/docker-build/docker/modules/python/eggroll
        cp -r ${package_dir}/examples ${SOURCE_DIR}/docker-build/docker/modules/python/examples
        cp -r ${package_dir}/fate.env ${SOURCE_DIR}/docker-build/docker/modules/python/fate.env

        # handle fateboard
        [ -d ${SOURCE_DIR}/docker-build/docker/modules/fateboard/fateboard ] && rm -rf ${SOURCE_DIR}/docker-build/docker/modules/fateboard/fateboard
        cp -r ${package_dir}/fateboard ${SOURCE_DIR}/docker-build/docker/modules/fateboard/fateboard

        # handle eggroll
        [ -d ${SOURCE_DIR}/docker-build/docker/modules/eggroll/python ] && rm -rf ${SOURCE_DIR}/docker-build/docker/modules/eggroll/python
        [ -d ${SOURCE_DIR}/docker-build/docker/modules/eggroll/eggroll ] && rm -rf ${SOURCE_DIR}/docker-build/docker/modules/eggroll/eggroll
        cp -r ${package_dir}/python ${SOURCE_DIR}/docker-build/docker/modules/eggroll/python
        cp -r ${package_dir}/eggroll/ ${SOURCE_DIR}/docker-build/docker/modules/eggroll/eggroll

        cd ${SOURCE_DIR}

        [ -f ${SOURCE_DIR}/docker-build/docker/modules/python-nn/requirements.txt ] && rm ${SOURCE_DIR}/docker-build/docker/modules/python-nn/requirements.txt
        ln ${SOURCE_DIR}/python/requirements.txt ${SOURCE_DIR}/docker-build/docker/modules/python-nn/requirements.txt
        for module in "python" "fateboard" "eggroll" "python-nn"; do
        echo "START BUILDING BASE IMAGE"
        cd ${WORKING_DIR}
                echo "### START BUILDING ${module} ###"
                docker build --build-arg version=${version} --build-arg fateboard_version=${fateboard_version} --build-arg PREFIX=${PREFIX} --build-arg BASE_TAG=${BASE_TAG} --no-cache -t ${PREFIX}/${module}:${TAG} -f ${SOURCE_DIR}/docker-build/docker/modules/${module}/Dockerfile ${SOURCE_DIR}/docker-build/docker/modules/${module}
                echo "### FINISH BUILDING ${module} ###"
                echo ""
        done

        # clean up
        rm -rf ${SOURCE_DIR}/docker-build/docker/modules/python/python
        rm -rf ${SOURCE_DIR}/docker-build/docker/modules/python/eggroll
        rm -rf ${SOURCE_DIR}/docker-build/docker/modules/fateboard/fateboard
        rm -rf ${SOURCE_DIR}/docker-build/docker/modules/eggroll/eggroll
        rm -rf ${SOURCE_DIR}/docker-build/docker/modules/eggroll/python

        echo ""
}

pushImage() {
        ## push image
        for module in "python" "eggroll" "fateboard" "python-nn"; do
                echo "### START PUSH ${module} ###"
                docker push ${PREFIX}/${module}:${TAG}
                echo "### FINISH PUSH ${module} ###"
                echo ""
        done
}

while [ "$1" != "" ]; do
        case $1 in
        package)
                package
                ;;
        base)
                buildBase
                ;;
        modules)
                buildModule
                ;;
        all)
                package
                buildBase
                buildModule
                ;;
        push)
                pushImage
                ;;
        esac
        shift
done

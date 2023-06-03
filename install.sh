#!/usr/bin/env bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
SOURCE_FILES=$(find ${SCRIPT_DIR} -not -path "*build/*" -type f -name "*.py")
DEST_DIR=/home/benjamin/anaconda3/envs/enfugue/lib/python3.10/site-packages/pibble/

for SOURCE_FILE in ${SOURCE_FILES[@]}; do
    REL_PATH=$(realpath --relative-to="${SCRIPT_DIR}" ${SOURCE_FILE})
    DEST_FILE=${DEST_DIR}${REL_PATH}
    if [ -f ${DEST_FILE} ]; then
        SOURCE_MD5=$(md5sum ${SOURCE_FILE} | awk '{print $1}')
        DEST_MD5=$(md5sum ${DEST_FILE} | awk '{print $1}')
        if [ "${SOURCE_MD5}" != "${DEST_MD5}" ]; then
            echo "Overwriting ${REL_PATH}"
            cp ${SOURCE_FILE} ${DEST_FILE}
        fi
    fi
done

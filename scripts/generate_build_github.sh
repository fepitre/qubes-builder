#!/bin/bash

set -e
set -o pipefail

# Allow DEBUG except for GITHUB_API_TOKEN
[ "$DEBUG" = "1" ] && set -x

# Defaulting to gpg2 if GNUPG is not set
[[ "x$GNUPG" = "x" ]] && GNUPG=gpg2

# Check if necessary variables are defined in the builder.conf
for var in GITHUB_API_FILE GITHUB_BUILD_TARGET SIGN_KEY RELEASE
do
    if [ "x${!var}" = "x" ]; then
        echo "Please provide $var in builder.conf"
        exit 1
    fi
done

if $GNUPG --list-secret-keys "$SIGN_KEY" &> /dev/null; then
    # Create TIMESTAMP with respect to UTC
    TIMESTAMP=$(date --utc +%Y%m%d%H%M)

    # GITHUB URL to post comment for trigger a build
    GITHUB_URL="https://api.github.com$GITHUB_BUILD_TARGET"

    # Create build command and sign it. Replace newline with
    # its corresponding character for JSON format
    data=$(echo "Build-template r$RELEASE $DIST $TIMESTAMP" | $GNUPG --digest-algo SHA256 --clearsign -u $SIGN_KEY | sed ':a;N;$!ba;s/\n/\\n/g')

    # POST json containing the signed build command
    echo "{\"body\": \"$data\"}" | curl -v --netrc-file "$GITHUB_API_FILE" POST "$GITHUB_URL" --data-binary @-
    
    # Remove 
else
    echo "Unable to find key $SIGN_KEY"; exit 1
fi


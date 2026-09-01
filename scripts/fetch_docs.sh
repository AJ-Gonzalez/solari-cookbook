#!/usr/bin/env bash
# Download docs.getsolari.com to markdown, one file per sitemap URL.
SECONDS=0
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=docs
mkdir -p "$OUT"

n=0
total=$(wc -l < /tmp/docs_urls.txt)
while read -r url; do
  rel="${url#https://docs.getsolari.com}"
  rel="${rel#/}"
  [ -z "$rel" ] && rel="index"
  html=$(curl -sL "$url")
  printf '%s' "$html" | python3 -c "
import sys, re
html = sys.stdin.read()
m = re.search(r'<article id=\"doc-article\".*?>(.*)</article>', html, re.S)
if not m:
    sys.exit('no article in ' + '$url')
print(m.group(1))
" | pandoc -f html -t gfm-raw_html --wrap=none -o "$OUT/$rel.md"
  # Source line so a local copy never masquerades as canon.
  sed -i "1i <!-- Source: $url -->" "$OUT/$rel.md"
  n=$((n + 1))
  echo "[$n/$total] $rel.md"
done < /tmp/docs_urls.txt

duration=$SECONDS
echo "Downloaded $n pages in $((duration / 60)):$((duration % 60))"

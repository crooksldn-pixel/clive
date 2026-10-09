#!/bin/bash
# Fetch the baseline URL list from a preview theme and extract SEO facts. usage: fetch_after.sh <SP> <theme id>
SP=$1; TID=$2; D=$SP/audit/after; mkdir -p $D/html $D/json; cd $D
UA='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
rm -f jar.txt; curl -sS -A "$UA" -b jar.txt -c jar.txt -L -o /dev/null "https://crooksldn.com/?preview_theme_id=$TID"
i=0; : > index.tsv
while IFS=$'\t' read f code u; do
  i=$((i+1)); n=$(printf %02d $i)
  c=$(curl -sS --retry 3 -A "$UA" -b jar.txt -c jar.txt -o html/$n.html -w '%{http_code}' "$u")
  printf 'html/%s.html\t%s\t%s\n' $n $c "$u" >> index.tsv
  if [ "$c" = 200 ] && [[ "$u" != *agents.md ]]; then
    grep -q "\"id\":$TID" html/$n.html || echo "NOT PREVIEW: $u"
    python3 -I $SP/tools/seo_extract.py html/$n.html "$u" > json/$n.json
  fi
done < $SP/audit/before/index.tsv

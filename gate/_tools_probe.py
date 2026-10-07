
import json, bench
names = list(bench.SPECIAL.keys())
json.dump(names, open("_toolnames.json","w",encoding="utf-8"), ensure_ascii=False)
print(len(names), names)

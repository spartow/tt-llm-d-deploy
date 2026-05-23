
.PHONY: route-lowest-cost route-lowest-latency route-slo-cost

route-lowest-cost:
	python benchmark/route_decision.py --policy lowest-cost --input-file benchmark/results/latest.csv

route-lowest-latency:
	python benchmark/route_decision.py --policy lowest-latency --input-file benchmark/results/latest.csv

route-slo-cost:
	python benchmark/route_decision.py --policy slo-aware-cost --latency-slo-ms 800 --input-file benchmark/results/latest.csv

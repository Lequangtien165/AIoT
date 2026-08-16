# ChokePoint Full-Frame Benchmark — Summary

_Generated from benchmark-output CSVs (8 runs, leave-one-session-out, full-frame probes)_

## Overall

| Metric | Value |
|---|---|
| Gallery crops | 32970 |
| Embedded OK | 32970 |
| Person probes (all runs) | 261912 |
| Closed-set queries | 251516 |
| Not-enrolled queries | 10396 |
| False accepts | 0.0 |
| Micro accuracy | 0.9886 |
| Macro accuracy | 0.9884 |
| Same-portal accuracy (micro) | 0.9982 |
| Same-portal accuracy (macro) | 0.9982 |
| Cross-portal accuracy (micro) | 0.9809 |
| Cross-portal accuracy (macro) | 0.9803 |
| Gallery embedding p50 (ms) | 4.7636 |
| Gallery embedding p95 (ms) | 6.9083 |
| Detection recall | 0.9998 |
| Detection precision | 0.6012 |
| Empty-frame false positive rate | 0.3711 |
| Probe cache id | 72948c48f1601dad |
| Probe cache build (s) | 6941.39 |
| Probe cache hits | 646338 |
| Probe cache misses | 0 |
| Probe cache hit rate | 1.0 |
| Unique probe frames | 92334 |
| Logical probe frames | 646338 |
| Cache reuse factor | 7.0 |
| Cache lookup p50 (ms) | 0.0003 |
| Cache lookup p95 (ms) | 0.0009 |

## Per-run summary

| Run | Gallery | Vectors | Probe frames | Person probes | Closed | Acc | FRR | MisID | Same acc | Cross acc | Not-enr | FAR | Wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| run-p1l-s1 | P1L S1 | 3564 | 81660 | 33513 | 30914 | 0.9838 | 0.0162 | 0.0 | 0.9999 | 0.9697 | 2599 | 0.0 | 8.01 |
| run-p1l-s2 | P1L S2 | 4289 | 81045 | 32705 | 30106 | 0.9867 | 0.0133 | 0.0 | 0.9996 | 0.976 | 2599 | 0.0 | 8.7 |
| run-p1l-s3 | P1L S3 | 4596 | 80250 | 32392 | 29793 | 0.9814 | 0.0186 | 0.0 | 0.9994 | 0.9668 | 2599 | 0.0 | 9.51 |
| run-p1l-s4 | P1L S4 | 4249 | 80850 | 32683 | 30084 | 0.9806 | 0.0194 | 0.0 | 0.9998 | 0.9647 | 2599 | 0.0 | 8.39 |
| run-p2e-s1 | P2E S1 | 3339 | 83556 | 33739 | 33739 | 0.9935 | 0.0065 | 0.0 | 0.9951 | 0.9921 | 0 | — | 6.79 |
| run-p2e-s2 | P2E S2 | 4429 | 83592 | 32608 | 32608 | 0.9931 | 0.0069 | 0.0 | 0.9963 | 0.9906 | 0 | — | 8.93 |
| run-p2e-s3 | P2E S3 | 3974 | 77307 | 32372 | 32372 | 0.995 | 0.005 | 0.0 | 0.9968 | 0.9936 | 0 | — | 7.72 |
| run-p2e-s4 | P2E S4 | 4530 | 78078 | 31900 | 31900 | 0.9933 | 0.0067 | 0.0 | 0.999 | 0.989 | 0 | — | 8.89 |

## Per session-camera probe accuracy

| Run | Probe | Scope | Correct | FR | MisID | Not-enr | FA | Person probes | Empty | Det. recall | Acc |
|---|---|---|---|---|---|---|---|---|---|---|---|
| run-p1l-s1 | P1L S2 C1 | same_portal_cross_session | 1981 | 0 | 0 | 0 | 0 | 1981 | 1782 | 1.0000 | 1.0000 |
| run-p1l-s1 | P1L S2 C2 | same_portal_cross_session | 1719 | 0 | 0 | 0 | 0 | 1719 | 2044 | 1.0000 | 1.0000 |
| run-p1l-s1 | P1L S2 C3 | same_portal_cross_session | 1011 | 0 | 0 | 0 | 0 | 1011 | 2752 | 1.0000 | 1.0000 |
| run-p1l-s1 | P1L S3 C1 | same_portal_cross_session | 1976 | 0 | 0 | 0 | 0 | 1976 | 2052 | 1.0000 | 1.0000 |
| run-p1l-s1 | P1L S3 C2 | same_portal_cross_session | 1843 | 0 | 0 | 0 | 0 | 1843 | 2185 | 1.0000 | 1.0000 |
| run-p1l-s1 | P1L S3 C3 | same_portal_cross_session | 1205 | 0 | 0 | 0 | 0 | 1205 | 2823 | 1.0000 | 1.0000 |
| run-p1l-s1 | P1L S4 C1 | same_portal_cross_session | 2011 | 0 | 0 | 0 | 0 | 2011 | 1817 | 1.0000 | 1.0000 |
| run-p1l-s1 | P1L S4 C2 | same_portal_cross_session | 1758 | 2 | 0 | 0 | 0 | 1760 | 2068 | 0.9994 | 0.9989 |
| run-p1l-s1 | P1L S4 C3 | same_portal_cross_session | 962 | 0 | 0 | 0 | 0 | 962 | 2866 | 1.0000 | 1.0000 |
| run-p1l-s1 | P2E S1 C1 | cross_portal | 255 | 14 | 0 | 76 | 0 | 345 | 2581 | 1.0000 | 0.9480 |
| run-p1l-s1 | P2E S1 C2 | cross_portal | 1360 | 33 | 0 | 222 | 0 | 1615 | 1311 | 1.0000 | 0.9763 |
| run-p1l-s1 | P2E S1 C3 | cross_portal | 1451 | 23 | 0 | 243 | 0 | 1717 | 1209 | 1.0000 | 0.9844 |
| run-p1l-s1 | P2E S2 C1 | cross_portal | 1112 | 29 | 0 | 175 | 0 | 1316 | 1598 | 1.0000 | 0.9746 |
| run-p1l-s1 | P2E S2 C2 | cross_portal | 1657 | 48 | 0 | 249 | 0 | 1954 | 960 | 1.0000 | 0.9718 |
| run-p1l-s1 | P2E S2 C3 | cross_portal | 1289 | 55 | 0 | 194 | 0 | 1538 | 1376 | 1.0000 | 0.9591 |
| run-p1l-s1 | P2E S3 C1 | cross_portal | 1896 | 16 | 0 | 324 | 0 | 2236 | 2773 | 0.9991 | 0.9916 |
| run-p1l-s1 | P2E S3 C2 | cross_portal | 1522 | 11 | 0 | 243 | 0 | 1776 | 3233 | 1.0000 | 0.9928 |
| run-p1l-s1 | P2E S3 C3 | cross_portal | 851 | 54 | 0 | 127 | 0 | 1032 | 3977 | 1.0000 | 0.9403 |
| run-p1l-s1 | P2E S4 C1 | cross_portal | 1628 | 65 | 0 | 271 | 0 | 1964 | 2788 | 1.0000 | 0.9616 |
| run-p1l-s1 | P2E S4 C2 | cross_portal | 1726 | 69 | 0 | 282 | 0 | 2077 | 2675 | 1.0000 | 0.9616 |
| run-p1l-s1 | P2E S4 C3 | cross_portal | 1201 | 81 | 0 | 193 | 0 | 1475 | 3277 | 1.0000 | 0.9368 |
| run-p1l-s2 | P1L S1 C1 | same_portal_cross_session | 1798 | 1 | 0 | 0 | 0 | 1799 | 1759 | 0.9994 | 0.9994 |
| run-p1l-s2 | P1L S1 C2 | same_portal_cross_session | 1523 | 1 | 0 | 0 | 0 | 1524 | 2034 | 0.9993 | 0.9993 |
| run-p1l-s2 | P1L S1 C3 | same_portal_cross_session | 579 | 1 | 0 | 0 | 0 | 580 | 2978 | 0.9983 | 0.9983 |
| run-p1l-s2 | P1L S3 C1 | same_portal_cross_session | 1975 | 1 | 0 | 0 | 0 | 1976 | 2052 | 1.0000 | 0.9995 |
| run-p1l-s2 | P1L S3 C2 | same_portal_cross_session | 1843 | 0 | 0 | 0 | 0 | 1843 | 2185 | 1.0000 | 1.0000 |
| run-p1l-s2 | P1L S3 C3 | same_portal_cross_session | 1205 | 0 | 0 | 0 | 0 | 1205 | 2823 | 1.0000 | 1.0000 |
| run-p1l-s2 | P1L S4 C1 | same_portal_cross_session | 2011 | 0 | 0 | 0 | 0 | 2011 | 1817 | 1.0000 | 1.0000 |
| run-p1l-s2 | P1L S4 C2 | same_portal_cross_session | 1758 | 2 | 0 | 0 | 0 | 1760 | 2068 | 0.9994 | 0.9989 |
| run-p1l-s2 | P1L S4 C3 | same_portal_cross_session | 962 | 0 | 0 | 0 | 0 | 962 | 2866 | 1.0000 | 1.0000 |
| run-p1l-s2 | P2E S1 C1 | cross_portal | 261 | 8 | 0 | 76 | 0 | 345 | 2581 | 1.0000 | 0.9703 |
| run-p1l-s2 | P2E S1 C2 | cross_portal | 1384 | 9 | 0 | 222 | 0 | 1615 | 1311 | 1.0000 | 0.9935 |
| run-p1l-s2 | P2E S1 C3 | cross_portal | 1470 | 4 | 0 | 243 | 0 | 1717 | 1209 | 1.0000 | 0.9973 |
| run-p1l-s2 | P2E S2 C1 | cross_portal | 1127 | 14 | 0 | 175 | 0 | 1316 | 1598 | 1.0000 | 0.9877 |
| run-p1l-s2 | P2E S2 C2 | cross_portal | 1670 | 35 | 0 | 249 | 0 | 1954 | 960 | 1.0000 | 0.9795 |
| run-p1l-s2 | P2E S2 C3 | cross_portal | 1305 | 39 | 0 | 194 | 0 | 1538 | 1376 | 1.0000 | 0.9710 |
| run-p1l-s2 | P2E S3 C1 | cross_portal | 1892 | 20 | 0 | 324 | 0 | 2236 | 2773 | 0.9991 | 0.9895 |
| run-p1l-s2 | P2E S3 C2 | cross_portal | 1523 | 10 | 0 | 243 | 0 | 1776 | 3233 | 1.0000 | 0.9935 |
| run-p1l-s2 | P2E S3 C3 | cross_portal | 840 | 65 | 0 | 127 | 0 | 1032 | 3977 | 1.0000 | 0.9282 |
| run-p1l-s2 | P2E S4 C1 | cross_portal | 1629 | 64 | 0 | 271 | 0 | 1964 | 2788 | 1.0000 | 0.9622 |
| run-p1l-s2 | P2E S4 C2 | cross_portal | 1736 | 59 | 0 | 282 | 0 | 2077 | 2675 | 1.0000 | 0.9671 |
| run-p1l-s2 | P2E S4 C3 | cross_portal | 1214 | 68 | 0 | 193 | 0 | 1475 | 3277 | 1.0000 | 0.9470 |
| run-p1l-s3 | P1L S1 C1 | same_portal_cross_session | 1798 | 1 | 0 | 0 | 0 | 1799 | 1759 | 0.9994 | 0.9994 |
| run-p1l-s3 | P1L S1 C2 | same_portal_cross_session | 1521 | 3 | 0 | 0 | 0 | 1524 | 2034 | 0.9993 | 0.9980 |
| run-p1l-s3 | P1L S1 C3 | same_portal_cross_session | 579 | 1 | 0 | 0 | 0 | 580 | 2978 | 0.9983 | 0.9983 |
| run-p1l-s3 | P1L S2 C1 | same_portal_cross_session | 1981 | 0 | 0 | 0 | 0 | 1981 | 1782 | 1.0000 | 1.0000 |
| run-p1l-s3 | P1L S2 C2 | same_portal_cross_session | 1719 | 0 | 0 | 0 | 0 | 1719 | 2044 | 1.0000 | 1.0000 |
| run-p1l-s3 | P1L S2 C3 | same_portal_cross_session | 1011 | 0 | 0 | 0 | 0 | 1011 | 2752 | 1.0000 | 1.0000 |
| run-p1l-s3 | P1L S4 C1 | same_portal_cross_session | 2011 | 0 | 0 | 0 | 0 | 2011 | 1817 | 1.0000 | 1.0000 |
| run-p1l-s3 | P1L S4 C2 | same_portal_cross_session | 1757 | 3 | 0 | 0 | 0 | 1760 | 2068 | 0.9994 | 0.9983 |
| run-p1l-s3 | P1L S4 C3 | same_portal_cross_session | 962 | 0 | 0 | 0 | 0 | 962 | 2866 | 1.0000 | 1.0000 |
| run-p1l-s3 | P2E S1 C1 | cross_portal | 250 | 19 | 0 | 76 | 0 | 345 | 2581 | 1.0000 | 0.9294 |
| run-p1l-s3 | P2E S1 C2 | cross_portal | 1345 | 48 | 0 | 222 | 0 | 1615 | 1311 | 1.0000 | 0.9655 |
| run-p1l-s3 | P2E S1 C3 | cross_portal | 1441 | 33 | 0 | 243 | 0 | 1717 | 1209 | 1.0000 | 0.9776 |
| run-p1l-s3 | P2E S2 C1 | cross_portal | 1119 | 22 | 0 | 175 | 0 | 1316 | 1598 | 1.0000 | 0.9807 |
| run-p1l-s3 | P2E S2 C2 | cross_portal | 1638 | 67 | 0 | 249 | 0 | 1954 | 960 | 1.0000 | 0.9607 |
| run-p1l-s3 | P2E S2 C3 | cross_portal | 1271 | 73 | 0 | 194 | 0 | 1538 | 1376 | 1.0000 | 0.9457 |
| run-p1l-s3 | P2E S3 C1 | cross_portal | 1895 | 17 | 0 | 324 | 0 | 2236 | 2773 | 0.9991 | 0.9911 |
| run-p1l-s3 | P2E S3 C2 | cross_portal | 1522 | 11 | 0 | 243 | 0 | 1776 | 3233 | 1.0000 | 0.9928 |
| run-p1l-s3 | P2E S3 C3 | cross_portal | 834 | 71 | 0 | 127 | 0 | 1032 | 3977 | 1.0000 | 0.9215 |
| run-p1l-s3 | P2E S4 C1 | cross_portal | 1633 | 60 | 0 | 271 | 0 | 1964 | 2788 | 1.0000 | 0.9646 |
| run-p1l-s3 | P2E S4 C2 | cross_portal | 1740 | 55 | 0 | 282 | 0 | 2077 | 2675 | 1.0000 | 0.9694 |
| run-p1l-s3 | P2E S4 C3 | cross_portal | 1212 | 70 | 0 | 193 | 0 | 1475 | 3277 | 1.0000 | 0.9454 |
| run-p1l-s4 | P1L S1 C1 | same_portal_cross_session | 1798 | 1 | 0 | 0 | 0 | 1799 | 1759 | 0.9994 | 0.9994 |
| run-p1l-s4 | P1L S1 C2 | same_portal_cross_session | 1523 | 1 | 0 | 0 | 0 | 1524 | 2034 | 0.9993 | 0.9993 |
| run-p1l-s4 | P1L S1 C3 | same_portal_cross_session | 579 | 1 | 0 | 0 | 0 | 580 | 2978 | 0.9983 | 0.9983 |
| run-p1l-s4 | P1L S2 C1 | same_portal_cross_session | 1981 | 0 | 0 | 0 | 0 | 1981 | 1782 | 1.0000 | 1.0000 |
| run-p1l-s4 | P1L S2 C2 | same_portal_cross_session | 1719 | 0 | 0 | 0 | 0 | 1719 | 2044 | 1.0000 | 1.0000 |
| run-p1l-s4 | P1L S2 C3 | same_portal_cross_session | 1011 | 0 | 0 | 0 | 0 | 1011 | 2752 | 1.0000 | 1.0000 |
| run-p1l-s4 | P1L S3 C1 | same_portal_cross_session | 1976 | 0 | 0 | 0 | 0 | 1976 | 2052 | 1.0000 | 1.0000 |
| run-p1l-s4 | P1L S3 C2 | same_portal_cross_session | 1843 | 0 | 0 | 0 | 0 | 1843 | 2185 | 1.0000 | 1.0000 |
| run-p1l-s4 | P1L S3 C3 | same_portal_cross_session | 1205 | 0 | 0 | 0 | 0 | 1205 | 2823 | 1.0000 | 1.0000 |
| run-p1l-s4 | P2E S1 C1 | cross_portal | 247 | 22 | 0 | 76 | 0 | 345 | 2581 | 1.0000 | 0.9182 |
| run-p1l-s4 | P2E S1 C2 | cross_portal | 1344 | 49 | 0 | 222 | 0 | 1615 | 1311 | 1.0000 | 0.9648 |
| run-p1l-s4 | P2E S1 C3 | cross_portal | 1434 | 40 | 0 | 243 | 0 | 1717 | 1209 | 1.0000 | 0.9729 |
| run-p1l-s4 | P2E S2 C1 | cross_portal | 1108 | 33 | 0 | 175 | 0 | 1316 | 1598 | 1.0000 | 0.9711 |
| run-p1l-s4 | P2E S2 C2 | cross_portal | 1643 | 62 | 0 | 249 | 0 | 1954 | 960 | 1.0000 | 0.9636 |
| run-p1l-s4 | P2E S2 C3 | cross_portal | 1279 | 65 | 0 | 194 | 0 | 1538 | 1376 | 1.0000 | 0.9516 |
| run-p1l-s4 | P2E S3 C1 | cross_portal | 1893 | 19 | 0 | 324 | 0 | 2236 | 2773 | 0.9991 | 0.9901 |
| run-p1l-s4 | P2E S3 C2 | cross_portal | 1521 | 12 | 0 | 243 | 0 | 1776 | 3233 | 1.0000 | 0.9922 |
| run-p1l-s4 | P2E S3 C3 | cross_portal | 842 | 63 | 0 | 127 | 0 | 1032 | 3977 | 1.0000 | 0.9304 |
| run-p1l-s4 | P2E S4 C1 | cross_portal | 1630 | 63 | 0 | 271 | 0 | 1964 | 2788 | 1.0000 | 0.9628 |
| run-p1l-s4 | P2E S4 C2 | cross_portal | 1722 | 73 | 0 | 282 | 0 | 2077 | 2675 | 1.0000 | 0.9593 |
| run-p1l-s4 | P2E S4 C3 | cross_portal | 1202 | 80 | 0 | 193 | 0 | 1475 | 3277 | 1.0000 | 0.9376 |
| run-p2e-s1 | P1L S1 C1 | cross_portal | 1796 | 3 | 0 | 0 | 0 | 1799 | 1759 | 0.9994 | 0.9983 |
| run-p2e-s1 | P1L S1 C2 | cross_portal | 1513 | 11 | 0 | 0 | 0 | 1524 | 2034 | 0.9993 | 0.9928 |
| run-p2e-s1 | P1L S1 C3 | cross_portal | 574 | 6 | 0 | 0 | 0 | 580 | 2978 | 0.9983 | 0.9897 |
| run-p2e-s1 | P1L S2 C1 | cross_portal | 1962 | 19 | 0 | 0 | 0 | 1981 | 1782 | 1.0000 | 0.9904 |
| run-p2e-s1 | P1L S2 C2 | cross_portal | 1706 | 13 | 0 | 0 | 0 | 1719 | 2044 | 1.0000 | 0.9924 |
| run-p2e-s1 | P1L S2 C3 | cross_portal | 1009 | 2 | 0 | 0 | 0 | 1011 | 2752 | 1.0000 | 0.9980 |
| run-p2e-s1 | P1L S3 C1 | cross_portal | 1950 | 26 | 0 | 0 | 0 | 1976 | 2052 | 1.0000 | 0.9868 |
| run-p2e-s1 | P1L S3 C2 | cross_portal | 1819 | 24 | 0 | 0 | 0 | 1843 | 2185 | 1.0000 | 0.9870 |
| run-p2e-s1 | P1L S3 C3 | cross_portal | 1202 | 3 | 0 | 0 | 0 | 1205 | 2823 | 1.0000 | 0.9975 |
| run-p2e-s1 | P1L S4 C1 | cross_portal | 1998 | 13 | 0 | 0 | 0 | 2011 | 1817 | 1.0000 | 0.9935 |
| run-p2e-s1 | P1L S4 C2 | cross_portal | 1743 | 17 | 0 | 0 | 0 | 1760 | 2068 | 0.9994 | 0.9903 |
| run-p2e-s1 | P1L S4 C3 | cross_portal | 954 | 8 | 0 | 0 | 0 | 962 | 2866 | 1.0000 | 0.9917 |
| run-p2e-s1 | P2E S2 C1 | same_portal_cross_session | 1316 | 0 | 0 | 0 | 0 | 1316 | 1598 | 1.0000 | 1.0000 |
| run-p2e-s1 | P2E S2 C2 | same_portal_cross_session | 1954 | 0 | 0 | 0 | 0 | 1954 | 960 | 1.0000 | 1.0000 |
| run-p2e-s1 | P2E S2 C3 | same_portal_cross_session | 1535 | 3 | 0 | 0 | 0 | 1538 | 1376 | 1.0000 | 0.9980 |
| run-p2e-s1 | P2E S3 C1 | same_portal_cross_session | 2230 | 6 | 0 | 0 | 0 | 2236 | 2773 | 0.9991 | 0.9973 |
| run-p2e-s1 | P2E S3 C2 | same_portal_cross_session | 1776 | 0 | 0 | 0 | 0 | 1776 | 3233 | 1.0000 | 1.0000 |
| run-p2e-s1 | P2E S3 C3 | same_portal_cross_session | 1026 | 6 | 0 | 0 | 0 | 1032 | 3977 | 1.0000 | 0.9942 |
| run-p2e-s1 | P2E S4 C1 | same_portal_cross_session | 1934 | 30 | 0 | 0 | 0 | 1964 | 2788 | 1.0000 | 0.9847 |
| run-p2e-s1 | P2E S4 C2 | same_portal_cross_session | 2064 | 13 | 0 | 0 | 0 | 2077 | 2675 | 1.0000 | 0.9937 |
| run-p2e-s1 | P2E S4 C3 | same_portal_cross_session | 1458 | 17 | 0 | 0 | 0 | 1475 | 3277 | 1.0000 | 0.9885 |
| run-p2e-s2 | P1L S1 C1 | cross_portal | 1795 | 4 | 0 | 0 | 0 | 1799 | 1759 | 0.9994 | 0.9978 |
| run-p2e-s2 | P1L S1 C2 | cross_portal | 1514 | 10 | 0 | 0 | 0 | 1524 | 2034 | 0.9993 | 0.9934 |
| run-p2e-s2 | P1L S1 C3 | cross_portal | 576 | 4 | 0 | 0 | 0 | 580 | 2978 | 0.9983 | 0.9931 |
| run-p2e-s2 | P1L S2 C1 | cross_portal | 1957 | 24 | 0 | 0 | 0 | 1981 | 1782 | 1.0000 | 0.9879 |
| run-p2e-s2 | P1L S2 C2 | cross_portal | 1695 | 24 | 0 | 0 | 0 | 1719 | 2044 | 1.0000 | 0.9860 |
| run-p2e-s2 | P1L S2 C3 | cross_portal | 1010 | 1 | 0 | 0 | 0 | 1011 | 2752 | 1.0000 | 0.9990 |
| run-p2e-s2 | P1L S3 C1 | cross_portal | 1940 | 36 | 0 | 0 | 0 | 1976 | 2052 | 1.0000 | 0.9818 |
| run-p2e-s2 | P1L S3 C2 | cross_portal | 1813 | 30 | 0 | 0 | 0 | 1843 | 2185 | 1.0000 | 0.9837 |
| run-p2e-s2 | P1L S3 C3 | cross_portal | 1203 | 2 | 0 | 0 | 0 | 1205 | 2823 | 1.0000 | 0.9983 |
| run-p2e-s2 | P1L S4 C1 | cross_portal | 2002 | 9 | 0 | 0 | 0 | 2011 | 1817 | 1.0000 | 0.9955 |
| run-p2e-s2 | P1L S4 C2 | cross_portal | 1736 | 24 | 0 | 0 | 0 | 1760 | 2068 | 0.9994 | 0.9864 |
| run-p2e-s2 | P1L S4 C3 | cross_portal | 957 | 5 | 0 | 0 | 0 | 962 | 2866 | 1.0000 | 0.9948 |
| run-p2e-s2 | P2E S1 C1 | same_portal_cross_session | 345 | 0 | 0 | 0 | 0 | 345 | 2581 | 1.0000 | 1.0000 |
| run-p2e-s2 | P2E S1 C2 | same_portal_cross_session | 1615 | 0 | 0 | 0 | 0 | 1615 | 1311 | 1.0000 | 1.0000 |
| run-p2e-s2 | P2E S1 C3 | same_portal_cross_session | 1717 | 0 | 0 | 0 | 0 | 1717 | 1209 | 1.0000 | 1.0000 |
| run-p2e-s2 | P2E S3 C1 | same_portal_cross_session | 2234 | 2 | 0 | 0 | 0 | 2236 | 2773 | 0.9991 | 0.9991 |
| run-p2e-s2 | P2E S3 C2 | same_portal_cross_session | 1776 | 0 | 0 | 0 | 0 | 1776 | 3233 | 1.0000 | 1.0000 |
| run-p2e-s2 | P2E S3 C3 | same_portal_cross_session | 1028 | 4 | 0 | 0 | 0 | 1032 | 3977 | 1.0000 | 0.9961 |
| run-p2e-s2 | P2E S4 C1 | same_portal_cross_session | 1937 | 27 | 0 | 0 | 0 | 1964 | 2788 | 1.0000 | 0.9863 |
| run-p2e-s2 | P2E S4 C2 | same_portal_cross_session | 2068 | 9 | 0 | 0 | 0 | 2077 | 2675 | 1.0000 | 0.9957 |
| run-p2e-s2 | P2E S4 C3 | same_portal_cross_session | 1465 | 10 | 0 | 0 | 0 | 1475 | 3277 | 1.0000 | 0.9932 |
| run-p2e-s3 | P1L S1 C1 | cross_portal | 1794 | 5 | 0 | 0 | 0 | 1799 | 1759 | 0.9994 | 0.9972 |
| run-p2e-s3 | P1L S1 C2 | cross_portal | 1511 | 13 | 0 | 0 | 0 | 1524 | 2034 | 0.9993 | 0.9915 |
| run-p2e-s3 | P1L S1 C3 | cross_portal | 579 | 1 | 0 | 0 | 0 | 580 | 2978 | 0.9983 | 0.9983 |
| run-p2e-s3 | P1L S2 C1 | cross_portal | 1957 | 24 | 0 | 0 | 0 | 1981 | 1782 | 1.0000 | 0.9879 |
| run-p2e-s3 | P1L S2 C2 | cross_portal | 1700 | 19 | 0 | 0 | 0 | 1719 | 2044 | 1.0000 | 0.9889 |
| run-p2e-s3 | P1L S2 C3 | cross_portal | 1007 | 4 | 0 | 0 | 0 | 1011 | 2752 | 1.0000 | 0.9960 |
| run-p2e-s3 | P1L S3 C1 | cross_portal | 1963 | 13 | 0 | 0 | 0 | 1976 | 2052 | 1.0000 | 0.9934 |
| run-p2e-s3 | P1L S3 C2 | cross_portal | 1824 | 19 | 0 | 0 | 0 | 1843 | 2185 | 1.0000 | 0.9897 |
| run-p2e-s3 | P1L S3 C3 | cross_portal | 1204 | 1 | 0 | 0 | 0 | 1205 | 2823 | 1.0000 | 0.9992 |
| run-p2e-s3 | P1L S4 C1 | cross_portal | 2005 | 6 | 0 | 0 | 0 | 2011 | 1817 | 1.0000 | 0.9970 |
| run-p2e-s3 | P1L S4 C2 | cross_portal | 1748 | 12 | 0 | 0 | 0 | 1760 | 2068 | 0.9994 | 0.9932 |
| run-p2e-s3 | P1L S4 C3 | cross_portal | 962 | 0 | 0 | 0 | 0 | 962 | 2866 | 1.0000 | 1.0000 |
| run-p2e-s3 | P2E S1 C1 | same_portal_cross_session | 345 | 0 | 0 | 0 | 0 | 345 | 2581 | 1.0000 | 1.0000 |
| run-p2e-s3 | P2E S1 C2 | same_portal_cross_session | 1615 | 0 | 0 | 0 | 0 | 1615 | 1311 | 1.0000 | 1.0000 |
| run-p2e-s3 | P2E S1 C3 | same_portal_cross_session | 1717 | 0 | 0 | 0 | 0 | 1717 | 1209 | 1.0000 | 1.0000 |
| run-p2e-s3 | P2E S2 C1 | same_portal_cross_session | 1315 | 1 | 0 | 0 | 0 | 1316 | 1598 | 1.0000 | 0.9992 |
| run-p2e-s3 | P2E S2 C2 | same_portal_cross_session | 1952 | 2 | 0 | 0 | 0 | 1954 | 960 | 1.0000 | 0.9990 |
| run-p2e-s3 | P2E S2 C3 | same_portal_cross_session | 1527 | 11 | 0 | 0 | 0 | 1538 | 1376 | 1.0000 | 0.9928 |
| run-p2e-s3 | P2E S4 C1 | same_portal_cross_session | 1948 | 16 | 0 | 0 | 0 | 1964 | 2788 | 1.0000 | 0.9919 |
| run-p2e-s3 | P2E S4 C2 | same_portal_cross_session | 2071 | 6 | 0 | 0 | 0 | 2077 | 2675 | 1.0000 | 0.9971 |
| run-p2e-s3 | P2E S4 C3 | same_portal_cross_session | 1466 | 9 | 0 | 0 | 0 | 1475 | 3277 | 1.0000 | 0.9939 |
| run-p2e-s4 | P1L S1 C1 | cross_portal | 1789 | 10 | 0 | 0 | 0 | 1799 | 1759 | 0.9994 | 0.9944 |
| run-p2e-s4 | P1L S1 C2 | cross_portal | 1508 | 16 | 0 | 0 | 0 | 1524 | 2034 | 0.9993 | 0.9895 |
| run-p2e-s4 | P1L S1 C3 | cross_portal | 579 | 1 | 0 | 0 | 0 | 580 | 2978 | 0.9983 | 0.9983 |
| run-p2e-s4 | P1L S2 C1 | cross_portal | 1949 | 32 | 0 | 0 | 0 | 1981 | 1782 | 1.0000 | 0.9838 |
| run-p2e-s4 | P1L S2 C2 | cross_portal | 1680 | 39 | 0 | 0 | 0 | 1719 | 2044 | 1.0000 | 0.9773 |
| run-p2e-s4 | P1L S2 C3 | cross_portal | 1009 | 2 | 0 | 0 | 0 | 1011 | 2752 | 1.0000 | 0.9980 |
| run-p2e-s4 | P1L S3 C1 | cross_portal | 1939 | 37 | 0 | 0 | 0 | 1976 | 2052 | 1.0000 | 0.9813 |
| run-p2e-s4 | P1L S3 C2 | cross_portal | 1816 | 27 | 0 | 0 | 0 | 1843 | 2185 | 1.0000 | 0.9853 |
| run-p2e-s4 | P1L S3 C3 | cross_portal | 1204 | 1 | 0 | 0 | 0 | 1205 | 2823 | 1.0000 | 0.9992 |
| run-p2e-s4 | P1L S4 C1 | cross_portal | 2005 | 6 | 0 | 0 | 0 | 2011 | 1817 | 1.0000 | 0.9970 |
| run-p2e-s4 | P1L S4 C2 | cross_portal | 1730 | 30 | 0 | 0 | 0 | 1760 | 2068 | 0.9994 | 0.9830 |
| run-p2e-s4 | P1L S4 C3 | cross_portal | 961 | 1 | 0 | 0 | 0 | 962 | 2866 | 1.0000 | 0.9990 |
| run-p2e-s4 | P2E S1 C1 | same_portal_cross_session | 345 | 0 | 0 | 0 | 0 | 345 | 2581 | 1.0000 | 1.0000 |
| run-p2e-s4 | P2E S1 C2 | same_portal_cross_session | 1615 | 0 | 0 | 0 | 0 | 1615 | 1311 | 1.0000 | 1.0000 |
| run-p2e-s4 | P2E S1 C3 | same_portal_cross_session | 1717 | 0 | 0 | 0 | 0 | 1717 | 1209 | 1.0000 | 1.0000 |
| run-p2e-s4 | P2E S2 C1 | same_portal_cross_session | 1314 | 2 | 0 | 0 | 0 | 1316 | 1598 | 1.0000 | 0.9985 |
| run-p2e-s4 | P2E S2 C2 | same_portal_cross_session | 1951 | 3 | 0 | 0 | 0 | 1954 | 960 | 1.0000 | 0.9985 |
| run-p2e-s4 | P2E S2 C3 | same_portal_cross_session | 1534 | 4 | 0 | 0 | 0 | 1538 | 1376 | 1.0000 | 0.9974 |
| run-p2e-s4 | P2E S3 C1 | same_portal_cross_session | 2233 | 3 | 0 | 0 | 0 | 2236 | 2773 | 0.9991 | 0.9987 |
| run-p2e-s4 | P2E S3 C2 | same_portal_cross_session | 1776 | 0 | 0 | 0 | 0 | 1776 | 3233 | 1.0000 | 1.0000 |
| run-p2e-s4 | P2E S3 C3 | same_portal_cross_session | 1031 | 1 | 0 | 0 | 0 | 1032 | 3977 | 1.0000 | 0.9990 |

## Per-camera probe accuracy (all runs, by camera index)

| Camera | Scope | Person probes | Closed | Acc |
|---|---|---|---|---|
| C1 | same_portal_cross_session | 40884 | 40884 | 0.9978 |
| C1 | cross_portal | 54512 | 51128 | 0.9853 |
| C2 | same_portal_cross_session | 42804 | 42804 | 0.9989 |
| C2 | cross_portal | 57072 | 53088 | 0.9816 |
| C3 | same_portal_cross_session | 28560 | 28560 | 0.9976 |
| C3 | cross_portal | 38080 | 35052 | 0.9736 |

## Probe cache

- Cache id: `72948c48f1601dad` (build fingerprint of models, providers, det_size=640, det_thresh=0.5, template_fill=0.9)
- Build: 6941.39 s for 92334 unique frames
- Read: 646338 hits / 0 misses, hit rate 1.0, reuse factor 7.0
- Lookup p50/p95: 0.0003 / 0.0009 ms

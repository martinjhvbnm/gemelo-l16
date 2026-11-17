"""Ejecuta gtfs2pt.py de SUMO (versiones antiguas) con pandas >= 2."""
import os, runpy, sys
import pandas as pd

if not hasattr(pd.DataFrame, "append"):
    def _append(self, other, ignore_index=False, **kw):
        if isinstance(other, (pd.Series, dict)):
            other = pd.DataFrame([other])
        elif isinstance(other, list):
            other = pd.concat(other) if other and isinstance(other[0], pd.DataFrame) else pd.DataFrame(other)
        return pd.concat([self, other], ignore_index=ignore_index)
    pd.DataFrame.append = _append
if not hasattr(pd.DataFrame, "iteritems"):
    pd.DataFrame.iteritems = pd.DataFrame.items
if not hasattr(pd.Series, "iteritems"):
    pd.Series.iteritems = pd.Series.items

script = os.path.abspath(sys.argv[1])
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(script))
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
runpy.run_path(script, run_name="__main__")

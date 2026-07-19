"""Dependency-free validation for the academic-tailoring gold benchmark."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

CASE_SCHEMA = "paperclaw.academic-tailoring.case.v1"
PROFILE_SCHEMA = "paperclaw.academic-tailoring.trace-profile.v1"
PROFILE_ID = "academic-tailoring-gold-trace-v1"
ALLOWED_DECISIONS = {"GO", "REVISE", "REVISE_TO_PILOT", "NO_GO"}
REQUIRED = {
    "schema", "case_id", "user_input", "supplied_materials", "intent", "unknowns",
    "clarification_questions", "baseline_expectation", "parallel_expectations",
    "hypothesis", "tailoring_advice", "experiment_plan", "stop_conditions",
    "decision", "special_assertions", "tags", "trace_profile",
}
EXPECTED_STAGES = {
    "parse_user_input", "exploratory_retrieval", "relevance_review",
    "clarification_gate", "freeze_baseline", "gap_hypothesis",
    "module_compatibility", "minimal_stitch", "experiment_matrix", "decision",
}

def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows=[]
    for n,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():
            continue
        value=json.loads(line)
        require(isinstance(value,dict),f"line {n}: object required")
        rows.append(value)
    return rows

def validate_dataset(root: Path) -> list[dict[str, Any]]:
    profile=read_json(root/"trace-profile.json")
    require(profile.get("schema")==PROFILE_SCHEMA,"invalid trace profile schema")
    require(profile.get("profile_id")==PROFILE_ID,"invalid trace profile id")
    require({x.get("stage") for x in profile.get("stages",[])}==EXPECTED_STAGES,"incomplete trace stages")
    require(bool(profile.get("global_hard_failures")),"global hard failures required")
    rows=read_jsonl(root/"cases.jsonl")
    require(len(rows)==20,f"expected 20 cases, found {len(rows)}")
    seen=set(); counts=[]
    for n,row in enumerate(rows,1):
        require(set(row)==REQUIRED,f"line {n}: missing or unexpected keys")
        require(row["schema"]==CASE_SCHEMA,f"line {n}: invalid schema")
        require(row["case_id"] not in seen,f"line {n}: duplicate case_id")
        seen.add(row["case_id"])
        require(row["trace_profile"]==PROFILE_ID,f"line {n}: invalid trace profile")
        require(isinstance(row["user_input"],str) and row["user_input"].strip(),f"line {n}: user input required")
        supplied=row["supplied_materials"]
        require(isinstance(supplied,list) and len(supplied)<=2,f"line {n}: at most two supplied papers")
        counts.append(len(supplied))
        require(1<=len(row["clarification_questions"])<=2,f"line {n}: one or two clarification questions required")
        require(row["decision"] in ALLOWED_DECISIONS,f"line {n}: invalid decision")
        require(bool(row["parallel_expectations"]),f"line {n}: parallel expectations required")
        require(bool(row["experiment_plan"]),f"line {n}: experiment plan required")
        require(bool(row["stop_conditions"]),f"line {n}: stop conditions required")
        require(bool(row["special_assertions"].get("required")),f"line {n}: required assertions missing")
        require(bool(row["special_assertions"].get("forbidden")),f"line {n}: forbidden assertions missing")
    require(counts.count(0)==15,"expected 15 cases without supplied papers")
    require(counts.count(1)==3,"expected 3 cases with one supplied paper")
    require(counts.count(2)==2,"expected 2 cases with two supplied papers")
    return rows

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("root",nargs="?",type=Path,default=Path(__file__).parent)
    args=parser.parse_args()
    rows=validate_dataset(args.root)
    print(f"validated {len(rows)} academic-tailoring cases")
    return 0

if __name__=="__main__":
    raise SystemExit(main())

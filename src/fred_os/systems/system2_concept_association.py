"""Reference S2 runtime: deterministic, bounded, non-mutating association overlays."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from math import exp, sqrt
from typing import Any, Dict, List
from .neurodynamic_kernel import (
    ChannelClass, ChannelState, CouplingSignal, FieldProfile, FieldState,
    GlobalParametersSnapshot, digest as field_digest, initial_state, transition,
)

def canonical_digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + sha256(data).hexdigest()

@dataclass(frozen=True)
class AssociationConfig:
    max_path_depth: int = 4
    min_path_confidence: float = .35
    association_threshold: float = .60
    max_candidates: int = 256
    max_output_associations: int = 64
    max_external_neighbors: int = 8
    transitive_decay: float = .85
    feedback_cycle_penalty: float = .65
    min_novelty: float = .35

@dataclass(frozen=True)
class NeurodynamicConfig:
    v_rest: float = .45
    capacitance: float = 1.0
    leak: float = .05
    dt: float = .1
    excitation_scale: float = 1.0

DEFAULT_CHANNELS = [
 {"from":"S1","role":"structural","g":.60,"a":.50,"E":.70,"alpha_base":.55,"beta_base":.45},
 {"from":"S3","role":"semantic","g":.45,"a":.45,"E":.65,"alpha_base":.50,"beta_base":.45},
 {"from":"S4","role":"ambiguity","g":.35,"a":.35,"E":.72,"alpha_base":.60,"beta_base":.55},
 {"from":"S4.COLOR","role":"color_algebraics","g":.25,"a":.25,"E":.62,"alpha_base":.35,"beta_base":.55},
 {"from":"TSC","role":"temporal","g":.35,"a":.40,"E":.64,"alpha_base":.40,"beta_base":.45},
 {"from":"CAG","role":"external_neighbor","g":.30,"a":.30,"E":.68,"alpha_base":.45,"beta_base":.60},
 {"from":"S8","role":"governance","g":.40,"a":.50,"E":.35,"alpha_base":.20,"beta_base":.70},
 {"from":"S12","role":"recovery","g":.45,"a":.50,"E":.45,"alpha_base":.20,"beta_base":.65}]

DEFAULT_CHANNELS_V2 = [
 ChannelState("S1:structural","S1","association_demand",ChannelClass.EXPLORATORY,.52,.45,.68,.50,.50),
 ChannelState("S3:semantic","S3","semantic_demand",ChannelClass.EXPLORATORY,.38,.42,.65,.48,.52),
 ChannelState("S4:ambiguity","S4","ambiguity",ChannelClass.EXPLORATORY,.30,.34,.70,.55,.58),
 ChannelState("S4:color","S4.COLOR","color_algebraics",ChannelClass.MODULATORY,.20,.25,.60,.35,.52),
 ChannelState("TSC:temporal","TSC","temporal_relevance",ChannelClass.MODULATORY,.28,.36,.62,.38,.48),
 ChannelState("CAG:external","CAG","external_neighbor",ChannelClass.EXPLORATORY,.24,.28,.66,.44,.62),
 ChannelState("S8:governance","S8","governance",ChannelClass.INHIBITORY,.42,.42,.33,.62,.30),
 ChannelState("S12:recovery","S12","recovery",ChannelClass.HOMEOSTATIC,.48,.42,.45,.65,.28),
]


def update_neurodynamic_state_explicit(args: Dict[str, Any]) -> Dict[str, Any]:
    """Advance serializable S2 FieldState through the shared control kernel."""
    gp = args.get("global_parameters", {})
    values = deepcopy(gp.get("values", {}))
    params = GlobalParametersSnapshot(
        revision=gp.get("revision", "gp-s2-draft5-default"),
        content_digest=gp.get("content_digest") or field_digest(values), values=values,
    )
    profile = FieldProfile(
        system="S2", version="s2-field-1.0", controlled_faculty="association-pressure",
        v_rest=.45, leak=.10, homeostasis_gain=.74, target_base=.48,
        target_drive_gain=.22, target_overload_drop=.11, target_restriction_drop=.10,
        external_weights={"novelty":.07,"ambiguity":.05,"association_demand":.10,"temporal_relevance":.03},
        feedback_weights={"overload":-.13,"redundancy":-.08,"governance_restriction":-.12,"recovery_signal":-.04},
    )
    state = FieldState.from_dict(args["field_state"]) if args.get("field_state") else initial_state(profile, DEFAULT_CHANNELS_V2, params)
    signals = [CouplingSignal(
        signal_id=s["signal_id"], source_system=s["source_system"], target_system=s["target_system"],
        signal_type=s["signal_type"], value=float(s["value"]), basis=tuple(s.get("basis", [])),
        authority=s.get("authority", "operational"),
    ) for s in args.get("signals", [])]
    result = transition(state, profile, args.get("load_metrics", {}), params, signals)
    policy = association_control_policy(result["field_state"]["voltage"])
    capsule = {
        "type":"S2_NeuralFieldCapsule","version":"2.0","system":"S2",
        "field_state":result["field_state"],"previous_voltage":result["previous_voltage"],
        "target_voltage":result["target_voltage"],"channels":result["field_state"]["channels"],
        "currents":result["currents"],"load_metrics":result["load_inputs"],
        "accepted_signals":result["accepted_signals"],"control_policy":policy,
        "global_parameters":{"revision":params.revision,"content_digest":params.content_digest},
        "transition_digest":result["transition_digest"],"hard_clamp_applied":result["hard_clamp_applied"],
        "model_semantics":result["model_semantics"],"mutates_source_graph":False,
    }
    receipt = {"receipt_id":"receipt-"+result["transition_digest"].split(":",1)[1][:16],
               "system":"S2","operation":"S2.FIELD.UPDATE","status":"success",
               "input_step":state.step,"output_step":result["field_state"]["step"],
               "transition_digest":result["transition_digest"],
               "global_parameters_digest":params.content_digest}
    return {"field_state":result["field_state"],
            "field_control_decision":{"policy":policy,"non_destructive":True},
            "neural_field_capsule":capsule,"execution_receipt":receipt}

def clamp(x: float) -> float: return max(0.0,min(1.0,float(x)))

def association_control_policy(v: float) -> Dict[str, Any]:
    if v < .35: state,vals="underactive",(4,192,8,32,.30)
    elif v < .60: state,vals="stable",(4,256,8,48,.35)
    elif v < .75: state,vals="exploratory",(3,128,6,24,.45)
    elif v < .88: state,vals="saturated",(2,64,4,8,.60)
    else: state,vals="critical",(1,24,0,4,.75)
    depth,candidates,external,output,min_conf=vals
    return {"operating_region":state,"max_path_depth":depth,"max_candidates":candidates,
      "max_external_neighbors":external,"max_output_associations":output,"min_compound_confidence":min_conf,
      "non_destructive":True}

def update_neurodynamic_state(current_v: float, channels: List[Dict[str, Any]], load: Dict[str, Any], config: NeurodynamicConfig = NeurodynamicConfig()) -> Dict[str, Any]:
    """HH-inspired load controller; operational analogy, not a biological simulation."""
    v=clamp(current_v); overload=clamp(load.get("overload",0)); ambiguity=clamp(load.get("ambiguity",0)); novelty=clamp(load.get("novelty",0)); redundancy=clamp(load.get("redundancy",0)); governance=clamp(load.get("governance_restriction",0)); demand=clamp(load.get("association_demand",0))
    updated=[]; channel_current=0.0
    for raw in channels:
        ch=deepcopy(raw); a=clamp(ch["a"]); role=ch["role"]
        role_demand=demand
        if role in {"ambiguity","color_algebraics"}: role_demand=clamp((ambiguity+novelty)/2)
        if role=="external_neighbor": role_demand=novelty
        if role in {"governance","recovery"}: role_demand=clamp(max(overload,governance))
        alpha=float(ch.get("alpha_base",.4))*(1-overload)*(1-v)*role_demand
        beta=float(ch.get("beta_base",.5))*clamp(overload+governance+redundancy)*(0.5+v)
        next_a=clamp(a+config.dt*(alpha*(1-a)-beta*a))
        current=float(ch["g"])*config.excitation_scale*next_a*(float(ch["E"])-v)
        ch.update({"a":round(next_a,6),"alpha":round(alpha,6),"beta":round(beta,6),"current":round(current,6)})
        updated.append(ch); channel_current+=current
    i_ext=.20*novelty+.20*ambiguity+.15*demand
    i_feedback=-.25*overload-.20*redundancy
    i_governance=-.30*governance
    i_leak=-config.leak*(v-config.v_rest)
    dv=(channel_current+i_ext+i_feedback+i_governance+i_leak)/config.capacitance
    next_v=clamp(v+config.dt*dv); policy=association_control_policy(next_v)
    return {"type":"S2_NeuralFieldCapsule","version":"1.0","system":"S2",
      "model_semantics":{"kind":"HH-inspired bounded control analogy","biological_fidelity_claimed":False},
      "neural_state":{"V":round(next_v,6),"V_rest":config.v_rest,"C":config.capacitance,"leak":config.leak,"dV_dt":round(dv,6),"equilibrium_deviation":round(next_v-config.v_rest,6)},
      "channels":updated,"currents":{"I_channels":round(channel_current,6),"I_ext":round(i_ext,6),"I_feedback":round(i_feedback,6),"I_governance":round(i_governance,6),"I_leak":round(i_leak,6),"dV":round(dv,6)},
      "load_metrics":{"overload":overload,"ambiguity":ambiguity,"novelty":novelty,"redundancy":redundancy,"governance_restriction":governance,"association_demand":demand},"control_policy":policy}

def apply_association_control_policy(base: AssociationConfig, policy: Dict[str, Any]) -> AssociationConfig:
    """Return a constrained config projection; never mutate candidate or canonical graphs."""
    return AssociationConfig(max_path_depth=min(base.max_path_depth,int(policy["max_path_depth"])),
      min_path_confidence=max(base.min_path_confidence,float(policy["min_compound_confidence"])),
      association_threshold=base.association_threshold,max_candidates=min(base.max_candidates,int(policy["max_candidates"])),
      max_output_associations=min(base.max_output_associations,int(policy["max_output_associations"])),
      max_external_neighbors=min(base.max_external_neighbors,int(policy["max_external_neighbors"])),
      transitive_decay=base.transitive_decay,feedback_cycle_penalty=base.feedback_cycle_penalty,min_novelty=base.min_novelty)

def accept_field_adjustment(channels: List[Dict[str, Any]], adjustment: Dict[str, Any]) -> List[Dict[str, Any]]:
    if adjustment.get("authorized") is not True: raise ValueError("UNAUTHORIZED_FIELD_ADJUSTMENT")
    allowed={"g_scale","alpha_scale","beta_scale"}
    if any(k not in allowed|{"adjustment_id","authorized","issuer","target_roles","reason"} for k in adjustment): raise ValueError("UNSUPPORTED_ADJUSTMENT")
    roles=set(adjustment.get("target_roles",[])); out=[]
    for raw in channels:
        ch=deepcopy(raw)
        if not roles or ch["role"] in roles:
            ch["g"]=clamp(float(ch["g"])*float(adjustment.get("g_scale",1)))
            ch["alpha_base"]=clamp(float(ch.get("alpha_base",.4))*float(adjustment.get("alpha_scale",1)))
            ch["beta_base"]=clamp(float(ch.get("beta_base",.5))*float(adjustment.get("beta_scale",1)))
        out.append(ch)
    return out

def source_ref(envelope: Dict[str, Any]) -> Dict[str, Any]:
    return {"graph_id": envelope["graph_id"], "graph_revision": envelope["graph_revision"],
            "content_digest": envelope["content_digest"], "schema_uri": envelope["payload_schema"]}

COMPOSITION_RULES = {
    ("supports", "influences"): ("evidence-reach", "evidence-lineage"),
    ("influences", "part-of"): ("construction-reach", "construction"),
    ("supports", "part-of"): ("provenance-reach", "provenance"),
    ("associated-with", "influences"): ("mnemonic-reach", "spatial-retrieval"),
    ("part-of", "refers-to"): ("provenance-feedback", "feedback-derived"),
}

def compose_path_semantics(edges: List[Dict[str, Any]], config: AssociationConfig) -> Dict[str, Any]:
    relations = [e.get("relation", "related-to") for e in edges]
    pair = tuple(relations[:2]) if len(relations) >= 2 else tuple(relations)
    relation, role = COMPOSITION_RULES.get(pair, ("association-reach", "structural-reach"))
    feedback = "refers-to" in relations or len(set(relations)) < len(relations) and len(relations) > 2
    penalty = config.feedback_cycle_penalty if feedback else 1.0
    if feedback and role == "structural-reach": role = "feedback-derived"
    return {"relation": relation, "path_role": role, "relations": relations,
            "feedback_path": feedback, "semantic_penalty": penalty}

def bounded_paths(envelope: Dict[str, Any], config: AssociationConfig) -> List[Dict[str, Any]]:
    edges = envelope["payload"]["edges"]
    adj: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        adj.setdefault(e["source"], []).append(e)
    out = []
    for start in sorted(adj):
        stack = [(start, [start], [], 1.0)]
        while stack and len(out) < config.max_candidates:
            current, nodes, used, confidence = stack.pop()
            if len(used) >= config.max_path_depth:
                continue
            for edge in reversed(sorted(adj.get(current, []), key=lambda x: x["id"])):
                target = edge["target"]
                if target in nodes:
                    continue
                edge_conf = float(edge.get("confidence", {}).get("value", 1.0))
                next_conf = confidence * edge_conf * (config.transitive_decay if used else 1.0)
                if next_conf < config.min_path_confidence:
                    continue
                next_nodes, next_used = nodes + [target], used + [edge["id"]]
                if len(next_used) >= 2:
                    path_edges = [next(e for e in edges if e["id"] == eid) for eid in next_used]
                    semantics = compose_path_semantics(path_edges, config)
                    scored_conf = next_conf * semantics["semantic_penalty"]
                    out.append({"source": start, "target": target, "node_path": next_nodes,
                                "edge_path": next_used, "confidence": round(scored_conf, 6), **semantics})
                stack.append((target, next_nodes, next_used, next_conf))
    return sorted(out, key=lambda p: (-p["confidence"], p["source"], p["target"], p["edge_path"]))[:config.max_candidates]

def propose(envelope: Dict[str, Any], config: AssociationConfig) -> Dict[str, Any]:
    before = canonical_digest(envelope)
    direct = {(e["source"], e["target"]) for e in envelope["payload"]["edges"]}
    candidates = []
    for path in bounded_paths(envelope, config):
        if (path["source"], path["target"]) in direct:
            continue
        key = f'{path["source"]}|{path["target"]}|{"/".join(path["edge_path"])}'
        candidates.append({"candidate_id": "s2c_" + sha256(key.encode()).hexdigest()[:16],
          "source": path["source"], "target": path["target"], "relation": path["relation"],
          "method": "bounded-transitive-path", "score": path["confidence"],
          "epistemic_state": "inferred", "support": path, "source_graph_ref": source_ref(envelope)})
    assert before == canonical_digest(envelope), "S2-NONMUTATION-001"
    return {"source_graph_ref": source_ref(envelope), "candidates": candidates[:config.max_candidates]}

def expand_external_neighbors(envelope: Dict[str, Any], proposals: List[Dict[str, Any]], config: AssociationConfig) -> Dict[str, Any]:
    """Validate host/retriever proposals; this function never invents external evidence."""
    node_ids = {n["id"] for n in envelope["payload"]["nodes"]}
    labels = {n.get("label", "").casefold() for n in envelope["payload"]["nodes"]}
    allowed_origins = {"retrieved-source", "model-prior", "analogical-hypothesis", "color-harmonic-hypothesis", "temporal-hypothesis", "cross-graph"}
    candidates, records = [], []
    per_anchor: Dict[str, int] = {}
    for i,p in enumerate(proposals):
        pid=p.get("proposal_id",f"external-{i}"); reasons=[]
        anchors=p.get("anchors",[]); origin=p.get("origin",{})
        if origin.get("type") not in allowed_origins: reasons.append("INVALID_ORIGIN")
        if not anchors or any(a not in node_ids for a in anchors): reasons.append("INVALID_ANCHOR")
        if p.get("label","").casefold() in labels: reasons.append("DUPLICATES_CANONICAL_NODE")
        if float(p.get("score",0)) < config.association_threshold: reasons.append("BELOW_THRESHOLD")
        if float(p.get("novelty",0)) < config.min_novelty: reasons.append("LOW_NOVELTY")
        if origin.get("type") == "retrieved-source" and not origin.get("source_ref"): reasons.append("MISSING_SOURCE_REF")
        if config.max_external_neighbors == 0: reasons.append("FIELD_POLICY_EXTERNAL_EXPANSION_DISABLED")
        if len(candidates) >= config.max_external_neighbors: reasons.append("GLOBAL_EXTERNAL_NEIGHBOR_BUDGET")
        if any(per_anchor.get(a,0) >= min(3, config.max_external_neighbors) for a in anchors): reasons.append("ANCHOR_BUDGET")
        disposition="rejected" if reasons else "admitted"
        records.append({"proposal_id":pid,"disposition":disposition,"reason_codes":reasons})
        if disposition == "admitted":
            for a in anchors: per_anchor[a]=per_anchor.get(a,0)+1
            key=f'{p["label"]}|{"/".join(sorted(anchors))}|{origin["type"]}'
            candidates.append({"candidate_id":"s2x_"+sha256(key.encode()).hexdigest()[:16],"candidate_kind":"external_neighbor",
              "label":p["label"],"node_type":p.get("node_type","concept"),"epistemic_state":"inferred",
              "origin":deepcopy(origin),"anchors":anchors,"relation_hypotheses":deepcopy(p.get("relation_hypotheses",[])),
              "score":float(p["score"]),"novelty":float(p["novelty"]),"explanatory_gain":float(p.get("explanatory_gain",p["score"])),
              "estimated_token_cost":max(1,int(p.get("estimated_token_cost",16))),"source_graph_ref":source_ref(envelope)})
    return {"source_graph_ref":source_ref(envelope),"external_candidates":candidates,"admission_records":records}

def select_explanatory_associations(candidates: List[Dict[str, Any]], max_output: int = 8) -> Dict[str, Any]:
    ranked=[]
    for c in candidates:
        gain=float(c.get("explanatory_gain",c.get("score",0)))
        novelty=float(c.get("novelty",.5)); cost=max(1,int(c.get("estimated_token_cost",16)))
        bpt=gain*novelty/cost
        ranked.append({**deepcopy(c),"benefit_per_token":round(bpt,8)})
    ranked.sort(key=lambda c:(-c["benefit_per_token"],-float(c.get("score",0)),c.get("candidate_id","")))
    return {"selected":ranked[:max_output],"deferred":ranked[max_output:],"selection_policy":"explanatory-gain*novelty/token-cost"}

def admit(candidate_set: Dict[str, Any], config: AssociationConfig) -> Dict[str, Any]:
    records, admitted = [], []
    seen = set()
    for c in sorted(candidate_set["candidates"], key=lambda x: (-x["score"], x["candidate_id"])):
        pair = (c["source"], c["target"], c["relation"])
        disposition, reasons = "admitted", []
        if c["score"] < config.association_threshold:
            disposition, reasons = "rejected", ["BELOW_THRESHOLD"]
        elif pair in seen:
            disposition, reasons = "rejected", ["DUPLICATE"]
        elif len(admitted) >= config.max_output_associations:
            disposition, reasons = "rejected", ["OUTPUT_BUDGET"]
        records.append({"candidate_id": c["candidate_id"], "disposition": disposition, "reason_codes": reasons})
        if disposition == "admitted":
            seen.add(pair); admitted.append(c)
    return {"source_graph_ref": candidate_set["source_graph_ref"], "admission_records": records, "admitted": admitted}

def build_overlay(ledger: Dict[str, Any], overlay_id: str) -> Dict[str, Any]:
    edges=[]
    for c in ledger["admitted"]:
        edges.append({"id":"s2e_"+c["candidate_id"][4:], "source":c["source"], "target":c["target"],
          "relation":c["relation"], "weight":c["score"], "confidence":{"value":c["score"],"method":"derived"},
          "epistemic_state":"inferred", "support":c["support"], "attributes":{"method":c["method"]}})
    overlay={"overlay_id":overlay_id,"source_graph_ref":deepcopy(ledger["source_graph_ref"]),"nodes":[],"edges":edges,
             "metadata":{"association_count":len(edges)}}
    return overlay

def evaluate_color_algebraics(left: Dict[str, Any], right: Dict[str, Any], harmony_tau: float = 35.0) -> Dict[str, Any]:
    """Reference CIELAB/CIE76 relation. No implicit cross-space conversion."""
    if left.get("space") != "CIELAB-D65" or right.get("space") != "CIELAB-D65":
        raise ValueError("COLOR_SPACE_CONVERSION_REQUIRED")
    if harmony_tau <= 0:
        raise ValueError("INVALID_HARMONY_TAU")
    if len(left.get("coordinates", [])) != 3 or len(right.get("coordinates", [])) != 3:
        raise ValueError("INVALID_COLOR_COORDINATES")
    delta_e = sqrt(sum((float(a)-float(b))**2 for a,b in zip(left["coordinates"],right["coordinates"])))
    harmony = exp(-delta_e/harmony_tau)
    uncertainty = 1.0-(1.0-float(left["uncertainty"]))*(1.0-float(right["uncertainty"]))
    return {"left_signature_id":left["signature_id"],"right_signature_id":right["signature_id"],
      "operation":"distance+harmony","space":"CIELAB-D65","metric":"CIE76",
      "delta_e":round(delta_e,6),"harmony":round(harmony,6),"uncertainty":round(uncertainty,6),
      "epistemic_state":"inferred","semantic_identity_claimed":False}

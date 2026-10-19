"""Durable estimated X API spend admission; not a provider billing cap.

A fresh reservation commits before each data API attempt. No refunds, including
uncertain transport outcomes. OAuth token exchange is outside the data catalogue.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Callable, Mapping
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from postriff_alpha.domain import AlphaError

PRICES = {
    "identity_read": 10000, "user_read": 10000, "post_read": 5000,
    "dm_read": 10000, "follows_read": 10000, "likes_read": 1000,
    "mutes_read": 1000, "blocks_read": 1000, "list_read": 5000,
    "post_write": 15000, "post_write_url": 200000,
    "interaction_create": 15000, "interaction_delete": 10000,
    "content_manage": 5000, "mute_delete": 5000,
    "bookmark": 5000, "list_create": 10000, "list_manage": 5000,
    "media_metadata": 5000, "dm_create": 15000,
}
CATALOG_VERSION = "x-ordinary-customer-2026-10-19-v1"
MAX_INTEGER = 10**15
MAX_RESOURCES = 10000


class XCostAdmissionError(AlphaError):
    def __init__(self, message="X API cost admission is unavailable.", *, status=503):
        super().__init__(message, status=status, code="x_cost_admission_denied")


def _integer(value, *, maximum=MAX_INTEGER):
    if isinstance(value, bool):
        raise ValueError("boolean is not a quantity")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        number = int(value)
    else:
        raise ValueError("integer required")
    if not 0 < number <= maximum:
        raise ValueError("quantity outside bounds")
    return number


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(timezone.utc)


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,239}", value):
        raise XCostAdmissionError("X API cost context identifier is missing or invalid.")
    return value


@dataclass(frozen=True)
class XCostPolicy:
    configured: bool = False
    reason: str = "missing_or_invalid_cost_policy"
    window_id: str = ""
    approval_ref: str = ""
    approval_expires_at: datetime | None = None
    price_evidence_ref: str = ""
    price_evidence_expires_at: datetime | None = None
    app_budget_micros: int = 0
    workspace_budget_micros: int = 0
    app_request_limit: int = 0
    workspace_request_limit: int = 0
    allowed_price_keys: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls, values: Mapping):
        try:
            def get(suffix):
                return values["RAFII_X_COST_" + suffix]
            raw = get("ALLOWED_PRICE_KEYS")
            if not isinstance(raw, str):
                raise ValueError("price keys must be a comma separated string")
            allowed = frozenset(part.strip() for part in raw.split(","))
            if not allowed or not allowed <= PRICES.keys():
                raise ValueError("unknown or missing allowed price key")
            return cls(
                configured=True, reason="configured",
                window_id=_identifier(get("WINDOW_ID")),
                approval_ref=_identifier(get("APPROVAL_REF")),
                approval_expires_at=_timestamp(get("APPROVAL_EXPIRES_AT")),
                price_evidence_ref=_identifier(get("PRICE_EVIDENCE_REF")),
                price_evidence_expires_at=_timestamp(get("PRICE_EVIDENCE_EXPIRES_AT")),
                app_budget_micros=_integer(get("APP_BUDGET_MICROS")),
                workspace_budget_micros=_integer(get("WORKSPACE_BUDGET_MICROS")),
                app_request_limit=_integer(get("APP_REQUEST_LIMIT")),
                workspace_request_limit=_integer(get("WORKSPACE_REQUEST_LIMIT")),
                allowed_price_keys=allowed,
            )
        except (KeyError, ValueError, TypeError, XCostAdmissionError):
            return cls()

    def active(self, now):
        return bool(self.configured and self.allowed_price_keys
            and self.approval_expires_at is not None and self.price_evidence_expires_at is not None
            and now < self.approval_expires_at and now < self.price_evidence_expires_at)

    @property
    def fingerprint(self):
        data = {
            "catalog": CATALOG_VERSION, "window": self.window_id,
            "approval": self.approval_ref,
            "approval_expires": self.approval_expires_at.isoformat() if self.approval_expires_at else None,
            "prices": self.price_evidence_ref,
            "prices_expires": self.price_evidence_expires_at.isoformat() if self.price_evidence_expires_at else None,
            "app_micros": self.app_budget_micros, "workspace_micros": self.workspace_budget_micros,
            "app_requests": self.app_request_limit, "workspace_requests": self.workspace_request_limit,
            "allowed": {key: PRICES[key] for key in sorted(self.allowed_price_keys)},
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def limits_hash(self):
        value = {"approval_ref":self.approval_ref,
            "approval_expires_at":self.approval_expires_at.astimezone(timezone.utc).isoformat(),
            "app_budget_micros":self.app_budget_micros,"workspace_budget_micros":self.workspace_budget_micros,
            "app_request_limit":self.app_request_limit,"workspace_request_limit":self.workspace_request_limit,
            "allowed_price_keys":sorted(self.allowed_price_keys)}
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()

    @property
    def evidence_hash(self):
        value = {"evidence_ref":self.price_evidence_ref,
            "expires_at":self.price_evidence_expires_at.astimezone(timezone.utc).isoformat(),
            "catalog_version":CATALOG_VERSION,"unit_prices":PRICES}
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()


@dataclass(frozen=True)
class XCostRequest:
    request_id: str
    workspace_id: str
    connection_id: str
    operation: str
    method: str
    endpoint: str
    price_key: str
    estimated_units: int
    estimated_micros: int


@dataclass(frozen=True)
class _Context:
    workspace_id: str
    connection_id: str
    operation: str
    reserve: Callable[[XCostRequest], str]


_context: ContextVar[_Context | None] = ContextVar("x_direct_cost_context", default=None)


@contextmanager
def bind_x_cost_context(*, workspace_id, connection_id, operation, reserve):
    if not callable(reserve):
        raise XCostAdmissionError("X API durable reservation callback is unavailable.")
    value = _Context(_identifier(workspace_id), _identifier(connection_id), _identifier(operation), reserve)
    token = _context.set(value)
    try:
        yield
    finally:
        _context.reset(token)


def _scalar(value):
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise XCostAdmissionError("X API request contains ambiguous resource bounds.")
        return value[0]
    return value


def _classify(method, path, body, query, max_resources):
    method = str(method).upper()
    if not isinstance(path, str):
        raise XCostAdmissionError("X API endpoint is invalid.")
    parsed = urlsplit(path)
    if parsed.fragment or parsed.username or parsed.password:
        raise XCostAdmissionError("X API endpoint is invalid.")
    if parsed.netloc and (parsed.scheme != "https" or parsed.netloc not in {"api.x.com", "api.twitter.com"}):
        raise XCostAdmissionError("X API endpoint is outside the official API.")
    concrete = parsed.path
    params = dict(parse_qs(parsed.query, keep_blank_values=True))
    if query is not None and not isinstance(query, Mapping):
        raise XCostAdmissionError("X API query is invalid.")
    for key, value in (query or {}).items():
        if key in params and str(_scalar(params[key])) != str(_scalar(value)):
            raise XCostAdmissionError("X API query has conflicting resource bounds.")
        params[key] = value
    if "expansions" in params and _scalar(params["expansions"]):
        raise XCostAdmissionError("X API expansions need a separately evidenced resource bound.")
    bound = None
    if max_resources is not None:
        try:
            bound = _integer(max_resources, maximum=MAX_RESOURCES)
        except ValueError as exc:
            raise XCostAdmissionError("X API resource bound is invalid.") from exc

    def finish(key, endpoint, units=1):
        if bound is not None and bound < units:
            raise XCostAdmissionError("X API resource bound understates the requested resources.")
        return key, endpoint, max(units, bound or 1)

    def many(key, endpoint, ids_key=None):
        try:
            if ids_key:
                raw = _scalar(params.get(ids_key))
                if not isinstance(raw, str) or not raw or any(not part for part in raw.split(",")):
                    raise ValueError("explicit IDs required")
                units = _integer(len(raw.split(",")), maximum=MAX_RESOURCES)
            else:
                units = _integer(_scalar(params.get("max_results")), maximum=MAX_RESOURCES)
        except ValueError as exc:
            raise XCostAdmissionError("X API list requests need an explicit provider resource bound.") from exc
        return finish(key, endpoint, units)

    if method == "GET":
        if concrete == "/2/users/me":
            return finish("identity_read", "/2/users/me")
        if re.fullmatch(r"/2/users/[0-9]+", concrete) or re.fullmatch(r"/2/users/by/username/[A-Za-z0-9_]+", concrete):
            return finish("user_read", "/2/users/:id")
        if concrete in {"/2/users", "/2/users/by"}:
            return many("user_read", concrete, "ids" if concrete == "/2/users" else "usernames")
        if re.fullmatch(r"/2/tweets/[0-9]+", concrete):
            return finish("post_read", "/2/tweets/:id")
        if concrete == "/2/tweets":
            return many("post_read", concrete, "ids")
        if re.fullmatch(r"/2/users/[0-9]+/(tweets|mentions|bookmarks|liked_tweets|timelines/reverse_chronological)", concrete):
            return many("post_read", "/2/users/:id/posts")
        if re.fullmatch(r"/2/users/[0-9]+/bookmarks/folders/[0-9]+", concrete):
            return many("post_read", "/2/users/:id/bookmarks/folders/:id")
        if re.fullmatch(r"/2/tweets/[0-9]+/quote_tweets", concrete) or concrete in {"/2/tweets/search/recent", "/2/tweets/search/all"}:
            return many("post_read", "/2/tweets/collection")
        if re.fullmatch(r"/2/users/[0-9]+/(followers|following)", concrete):
            return many("follows_read", "/2/users/:id/" + concrete.rsplit("/", 1)[1])
        if re.fullmatch(r"/2/users/[0-9]+/(blocking|muting)", concrete):
            # Returned user resources use the conservative full user price.
            return many("user_read", "/2/users/:id/" + concrete.rsplit("/", 1)[1])
        if re.fullmatch(r"/2/tweets/[0-9]+/(liking_users|retweeted_by)", concrete):
            return many("user_read", "/2/tweets/:id/users")
        if re.fullmatch(r"/2/lists/[0-9]+", concrete):
            return finish("list_read", "/2/lists/:id")
        if re.fullmatch(r"/2/lists/[0-9]+/tweets", concrete):
            return many("post_read", "/2/lists/:id/tweets")
        if re.fullmatch(r"/2/lists/[0-9]+/(members|followers)", concrete):
            return many("user_read", "/2/lists/:id/users")
        if re.fullmatch(r"/2/users/[0-9]+/(owned_lists|followed_lists|list_memberships|pinned_lists)", concrete):
            return many("list_read", "/2/users/:id/lists")
        if concrete == "/2/dm_events" or re.fullmatch(r"/2/dm_conversations/(with/[0-9]+|[0-9]+(-[0-9]+)?)/dm_events", concrete):
            return many("dm_read", "/2/dm_events")
        if re.fullmatch(r"/2/dm_events/[0-9]+", concrete):
            return finish("dm_read", "/2/dm_events/:id")
    if method == "POST" and concrete == "/2/tweets":
        plain = isinstance(body, Mapping) and set(body) <= {"text","reply","edit_options"} and isinstance(body.get("text"), str)
        if plain:
            plain = not any(char in body["text"] for char in ".:/\\\u3002\uff0e\uff61\u2024")
        return finish("post_write" if plain else "post_write_url", "/2/tweets")
    if method == "DELETE" and re.fullmatch(r"/2/tweets/[0-9]+", concrete):
        return finish("content_manage", "/2/tweets/:id")
    if method == "PUT" and re.fullmatch(r"/2/tweets/[0-9]+/hidden", concrete):
        return finish("content_manage", "/2/tweets/:id/hidden")
    if re.fullmatch(r"/2/users/[0-9]+/(likes|retweets|following|blocking|muting)(/[0-9]+)?", concrete):
        parts = concrete.split("/")
        if method == "POST" and len(parts) == 5:
            return finish("interaction_create", "/2/users/:id/" + parts[4])
        if method == "DELETE" and len(parts) == 6:
            return finish("mute_delete" if parts[4] == "muting" else "interaction_delete", "/2/users/:id/" + parts[4] + "/:target")
    if re.fullmatch(r"/2/users/[0-9]+/bookmarks(/[0-9]+)?", concrete):
        if (method == "POST" and len(concrete.split("/")) == 5) or (method == "DELETE" and len(concrete.split("/")) == 6):
            return finish("bookmark", "/2/users/:id/bookmarks")
    if method == "POST" and concrete == "/2/lists":
        return finish("list_create", "/2/lists")
    if method in {"PUT", "DELETE"} and re.fullmatch(r"/2/lists/[0-9]+", concrete):
        return finish("list_manage", "/2/lists/:id")
    if (method == "POST" and re.fullmatch(r"/2/lists/[0-9]+/members", concrete)) or (method == "DELETE" and re.fullmatch(r"/2/lists/[0-9]+/members/[0-9]+", concrete)):
        return finish("list_manage", "/2/lists/:id/members")
    if method == "POST" and concrete == "/2/media/metadata":
        return finish("media_metadata", concrete)
    if method == "POST" and (concrete == "/2/dm_conversations" or re.fullmatch(r"/2/dm_conversations/(with/[0-9]+|[0-9]+(-[0-9]+)?)/messages", concrete)):
        return finish("dm_create", "/2/dm_conversations/messages")
    raise XCostAdmissionError("Unavailable — X API pricing evidence is missing for this endpoint.")


def estimate_request_cost_micros(*, method, path, body=None, query=None, max_resources=None):
    key, _endpoint, units = _classify(method, path, body, query, max_resources)
    return units * PRICES[key]


def admit_x_request(*, method, path, body=None, query=None, max_resources=None):
    context = _context.get()
    if context is None:
        raise XCostAdmissionError("X API request has no server-bound cost context.")
    try:
        key, endpoint, units = _classify(method, path, body, query, max_resources)
    except (ValueError, TypeError, OverflowError) as exc:
        raise XCostAdmissionError("X API request pricing inputs are invalid.") from exc
    request = XCostRequest(str(uuid4()), context.workspace_id, context.connection_id, context.operation,
        str(method).upper(), endpoint, key, units, units * PRICES[key])
    try:
        reservation_id = context.reserve(request)
    except XCostAdmissionError:
        raise
    except Exception as exc:
        raise XCostAdmissionError("X API durable reservation could not be committed.") from exc
    if not isinstance(reservation_id, str) or not reservation_id.strip():
        raise XCostAdmissionError("X API durable reservation did not return an identifier.")
    return reservation_id


def _row(value, names):
    if value is None:
        return {}
    return dict(value) if isinstance(value, Mapping) else dict(zip(names, value))



class XCostController:
    def __init__(self, connection_factory, policy=None, app_key="", clock=None):
        self.connection_factory = connection_factory
        self.policy = policy if isinstance(policy,XCostPolicy) else XCostPolicy()
        self.app_key = app_key
        self.clock = clock or (lambda:datetime.now(timezone.utc))

    def _now(self):
        value=self.clock()
        if type(value) in (int,float):
            value=datetime.fromtimestamp(value,timezone.utc)
        if isinstance(value,str):
            value=_timestamp(value)
        if not isinstance(value,datetime) or value.utcoffset() is None:
            raise XCostAdmissionError("Invalid X admission clock.")
        return value.astimezone(timezone.utc)

    @property
    def configured(self):
        try:
            _identifier(self.app_key)
            return self.policy.configured and callable(self.connection_factory)
        except Exception:
            return False

    @property
    def ready(self):
        try:
            return self.configured and self.policy.active(self._now())
        except Exception:
            return False

    @property
    def status(self):
        return {"configured":self.configured,"ready":self.ready,
                "admission":"estimated_spend_only","provider_billing_cap_verified":False}

    def context(self, workspace_id, connection_id, operation):
        return bind_x_cost_context(workspace_id=workspace_id,connection_id=connection_id,
                                   operation=operation,reserve=self.reserve)

    @contextmanager
    def _transaction(self, readonly=False):
        try:
            with self.connection_factory() as db:
                if int(db.info.transaction_status)!=0:
                    raise XCostAdmissionError("Admission requires an independent transaction.")
                with db.transaction():
                    with db.cursor() as cur:
                        if readonly:
                            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                        cur.execute("SET LOCAL lock_timeout = '5s'")
                        cur.execute("SET LOCAL statement_timeout = '10s'")
                        yield cur
        except XCostAdmissionError:
            raise
        except Exception as error:
            raise XCostAdmissionError("Durable X cost admission is unavailable.") from error

    @staticmethod
    def _fetch(cur, sql, args=()):
        cur.execute(sql,args)
        row=cur.fetchone()
        if row is None or isinstance(row,dict):
            return row
        return dict(zip((column[0] for column in cur.description),row))

    def _grant_values(self):
        p=self.policy
        return (p.approval_expires_at,p.limits_hash,p.app_budget_micros,
            p.workspace_budget_micros,p.app_request_limit,p.workspace_request_limit,sorted(p.allowed_price_keys))

    def _grant_matches(self,row):
        fields=("approval_expires_at","limits_hash","app_budget_micros","workspace_budget_micros",
                "app_request_limit","workspace_request_limit","allowed_price_keys")
        return row is not None and tuple(row[name] for name in fields)==self._grant_values()

    def _active(self,cur,lock=False):
        return self._fetch(cur,"""SELECT g.*,a.active_price_evidence_hash,e.evidence_ref,
            e.expires_at AS evidence_expires_at,e.unit_prices,clock_timestamp() AS db_now
            FROM postriff.x_cost_app_activation a
            JOIN postriff.x_cost_grants g ON g.app_key=a.app_key AND g.approval_ref=a.active_approval_ref
            JOIN postriff.x_cost_price_evidence e ON e.app_key=a.app_key AND e.evidence_hash=a.active_price_evidence_hash
            WHERE a.app_key=%s"""+(" FOR UPDATE OF g" if lock else ""),(self.app_key,))

    def _matches(self,row):
        p=self.policy
        return bool(row and row["approval_ref"]==p.approval_ref and self._grant_matches(row)
            and row["active_price_evidence_hash"]==p.evidence_hash
            and row["evidence_ref"]==p.price_evidence_ref
            and row["evidence_expires_at"]==p.price_evidence_expires_at
            and isinstance(row["unit_prices"],dict) and row["unit_prices"]==PRICES
            and all(type(v) is int for v in row["unit_prices"].values())
            and p.active(row["db_now"]) and self.ready)

    @staticmethod
    def _fits(grant,workspace,amount,requests):
        workspace=workspace or {"estimated_micros":0,"request_count":0}
        return (grant["estimated_micros"]+amount<=grant["app_budget_micros"]
            and grant["request_count"]+requests<=grant["app_request_limit"]
            and workspace["estimated_micros"]+amount<=grant["workspace_budget_micros"]
            and workspace["request_count"]+requests<=grant["workspace_request_limit"])

    def _live(self,cur):
        now=self._fetch(cur,"SELECT clock_timestamp() AS now")["now"]
        if not self.policy.active(now) or not self.policy.active(self._now()):
            raise XCostAdmissionError("X cost approval or price evidence has expired.")

    def activate(self,activation_ref,expected_generation=0,expected_approval_ref=None):
        """Explicit administrator operation. NEVER called by execution or configuration."""
        if not self.ready:
            raise XCostAdmissionError("X cost policy is not ready.")
        _identifier(activation_ref)
        if expected_approval_ref is not None:
            _identifier(expected_approval_ref)
        if type(expected_generation) is not int or expected_generation<0:
            raise XCostAdmissionError("Invalid expected X activation generation.")
        p=self.policy
        with self._transaction() as cur:
            cur.execute("INSERT INTO postriff.x_cost_app_activation(app_key) VALUES(%s) ON CONFLICT DO NOTHING",(self.app_key,))
            active=self._fetch(cur,"SELECT * FROM postriff.x_cost_app_activation WHERE app_key=%s FOR UPDATE",(self.app_key,))
            if (active["generation"],active["active_approval_ref"])!=(expected_generation,expected_approval_ref):
                raise XCostAdmissionError("X app activation changed; explicit review is required.")
            cur.execute("""INSERT INTO postriff.x_cost_grants(app_key,approval_ref,approval_expires_at)
                VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",(self.app_key,p.approval_ref,p.approval_expires_at))
            grant=self._fetch(cur,"""SELECT * FROM postriff.x_cost_grants
                WHERE app_key=%s AND approval_ref=%s FOR UPDATE""",(self.app_key,p.approval_ref))
            if grant["limits_hash"] is None:
                if p.approval_expires_at>grant["approval_expires_at"]:
                    raise XCostAdmissionError("Imported approval expiry cannot be extended.")
                cur.execute("""UPDATE postriff.x_cost_grants SET approval_expires_at=%s,limits_hash=%s,
                    app_budget_micros=%s,workspace_budget_micros=%s,app_request_limit=%s,
                    workspace_request_limit=%s,allowed_price_keys=%s WHERE app_key=%s AND approval_ref=%s""",
                    (*self._grant_values(),self.app_key,p.approval_ref))
            elif not self._grant_matches(grant):
                raise XCostAdmissionError("Existing X approval limits are immutable.")
            cur.execute("""INSERT INTO postriff.x_cost_price_evidence
                (app_key,evidence_hash,evidence_ref,expires_at,unit_prices)
                VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""",
                (self.app_key,p.evidence_hash,p.price_evidence_ref,p.price_evidence_expires_at,json.dumps(PRICES,sort_keys=True)))
            generation=active["generation"]+1
            cur.execute("""UPDATE postriff.x_cost_app_activation SET active_approval_ref=%s,
                active_price_evidence_hash=%s,activation_ref=%s,generation=%s WHERE app_key=%s""",
                (p.approval_ref,p.evidence_hash,activation_ref,generation,self.app_key))
            if not self._matches(self._active(cur)):
                raise XCostAdmissionError("X activation evidence does not match the configured policy.")
            self._live(cur)
        return generation

    def eligible(self,amount,workspace_id,request_count=1):
        try:
            if not self.ready or type(amount) is not int or not 0<amount<=MAX_INTEGER:
                return False
            if type(request_count) is not int or not 0<request_count<=MAX_INTEGER:
                return False
            _identifier(workspace_id)
            with self._transaction(readonly=True) as cur:
                grant=self._active(cur)
                if not self._matches(grant):
                    return False
                workspace=self._fetch(cur,"""SELECT estimated_micros,request_count FROM postriff.x_cost_grant_workspaces
                    WHERE app_key=%s AND approval_ref=%s AND workspace_id=%s""",(self.app_key,self.policy.approval_ref,workspace_id))
                return self._fits(grant,workspace,amount,request_count)
        except Exception:
            return False

    def eligible_request(self,request,workspace_id):
        try:
            if request.operation_id=="posts.thread":
                count,amount=request.max_billable_resources,request.estimated_cost_micros
                posts=request.body.get("posts")
                if (type(count) is not int or count%4 or not isinstance(posts,(tuple,list))
                        or not 2<=len(posts)<=25 or count!=len(posts)*4 or type(amount) is not int
                        or amount!=len(posts)*(PRICES["post_write_url"]+3*PRICES["post_read"])):
                    return False
                return ({"post_write_url","post_read"}<=self.policy.allowed_price_keys
                    and self.eligible(amount,workspace_id,request_count=count))
            key,_,units=_classify(request.method,request.path,request.body,request.query,request.max_billable_resources)
            return key in self.policy.allowed_price_keys and self.eligible(units*PRICES[key],workspace_id)
        except Exception:
            return False

    def reserve(self,request):
        if not self.ready or not isinstance(request,XCostRequest):
            raise XCostAdmissionError("X cost admission requires a configured typed request.")
        p=self.policy
        for value in (request.request_id,request.workspace_id,request.connection_id,request.operation):
            _identifier(value)
        if (request.price_key not in p.allowed_price_keys or request.price_key not in PRICES
                or type(request.estimated_units) is not int or not 0<request.estimated_units<=MAX_RESOURCES
                or type(request.estimated_micros) is not int or not 0<request.estimated_micros<=MAX_INTEGER
                or request.estimated_micros!=request.estimated_units*PRICES[request.price_key]):
            raise XCostAdmissionError("X request pricing is unknown, disallowed, or inconsistent.")
        scope=(self.app_key,p.approval_ref,request.workspace_id)
        with self._transaction() as cur:
            self._fetch(cur,"SELECT app_key FROM postriff.x_cost_app_activation WHERE app_key=%s FOR UPDATE",(self.app_key,))
            grant=self._active(cur,lock=True)
            if not self._matches(grant):
                raise XCostAdmissionError("X approval is inactive or its evidence has changed.")
            cur.execute("""INSERT INTO postriff.x_cost_grant_workspaces(app_key,approval_ref,workspace_id)
                VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",scope)
            workspace=self._fetch(cur,"""SELECT * FROM postriff.x_cost_grant_workspaces
                WHERE app_key=%s AND approval_ref=%s AND workspace_id=%s FOR UPDATE""",scope)
            if not self._fits(grant,workspace,request.estimated_micros,1):
                raise XCostAdmissionError("X approved estimated spend or request allowance is exhausted.",status=429)
            cur.execute("""INSERT INTO postriff.x_cost_windows
                (app_key,window_id,policy_hash,approval_ref,approval_expires_at,price_evidence_ref,price_evidence_expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (self.app_key,p.window_id,p.fingerprint,p.approval_ref,p.approval_expires_at,p.price_evidence_ref,p.price_evidence_expires_at))
            legacy=self._fetch(cur,"""SELECT approval_ref FROM postriff.x_cost_windows
                WHERE app_key=%s AND window_id=%s FOR UPDATE""",(self.app_key,p.window_id))
            if legacy["approval_ref"]!=p.approval_ref:
                raise XCostAdmissionError("An X audit window cannot change its approval.")
            old_scope=(self.app_key,p.window_id,request.workspace_id)
            cur.execute("""INSERT INTO postriff.x_cost_workspaces(app_key,window_id,workspace_id)
                VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",old_scope)
            self._fetch(cur,"""SELECT workspace_id FROM postriff.x_cost_workspaces
                WHERE app_key=%s AND window_id=%s AND workspace_id=%s FOR UPDATE""",old_scope)
            self._live(cur)
            cur.execute("""INSERT INTO postriff.x_cost_reservations
                (request_id,app_key,window_id,workspace_id,connection_id,operation,method,endpoint,price_key,
                 estimated_units,estimated_micros,policy_hash,cost_approval_ref,admission_version,price_evidence_hash)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,2,%s)""",
                (request.request_id,self.app_key,p.window_id,request.workspace_id,request.connection_id,
                 request.operation,request.method,request.endpoint,request.price_key,request.estimated_units,
                 request.estimated_micros,p.fingerprint,p.approval_ref,p.evidence_hash))
            cur.execute("""UPDATE postriff.x_cost_grants SET estimated_micros=estimated_micros+%s,
                request_count=request_count+1 WHERE app_key=%s AND approval_ref=%s""",
                (request.estimated_micros,self.app_key,p.approval_ref))
            cur.execute("""UPDATE postriff.x_cost_grant_workspaces SET estimated_micros=estimated_micros+%s,
                request_count=request_count+1 WHERE app_key=%s AND approval_ref=%s AND workspace_id=%s""",
                (request.estimated_micros,*scope))
            cur.execute("""UPDATE postriff.x_cost_windows SET estimated_micros=estimated_micros+%s,
                request_count=request_count+1 WHERE app_key=%s AND window_id=%s""",
                (request.estimated_micros,self.app_key,p.window_id))
            cur.execute("""UPDATE postriff.x_cost_workspaces SET estimated_micros=estimated_micros+%s,
                request_count=request_count+1 WHERE app_key=%s AND window_id=%s AND workspace_id=%s""",
                (request.estimated_micros,*old_scope))
            self._live(cur)
        return request.request_id

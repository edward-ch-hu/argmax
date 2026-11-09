"""The 2026 Google Ads API access model: no developer token, access levels per Cloud project, Explorer without
Keyword Planner. No network."""
from types import SimpleNamespace

import ads_client
import config
import doctor
import get_refresh_token
import keyword_review
import pytest
from conftest import EXAMPLE, make
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v26.errors.types.authorization_error import AuthorizationErrorEnum
from google.ads.googleads.v26.errors.types.errors import ErrorCode, GoogleAdsError, GoogleAdsFailure
from google.ads.googleads.v26.services.types.keyword_plan_idea_service import GenerateKeywordIdeasRequest

OAUTH = {"client_id": "id.apps.googleusercontent.com", "client_secret": "s", "refresh_token": "r"}


def test_client_settings_drop_placeholders_and_need_no_developer_token(tmp_path):
    path = tmp_path / "google-ads.yaml"
    path.write_text("client_id: a\nclient_secret: b\nrefresh_token: c\ndeveloper_token: INSERT_DEVELOPER_TOKEN\n"
                    "login_customer_id: ''\n")
    settings = ads_client.client_settings(path=path)
    assert settings == {"client_id": "a", "client_secret": "b", "refresh_token": "c", "use_proto_plus": True}
    assert ads_client.missing_credentials(settings) == []
    env = {"GOOGLE_ADS_CLIENT_ID": "a", "GOOGLE_ADS_CLIENT_SECRET": "b", "GOOGLE_ADS_REFRESH_TOKEN": "c",
           "GOOGLE_ADS_DEVELOPER_TOKEN": "", "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "111-222-3333",
           "GOOGLE_ADS_USE_PROTO_PLUS": "True"}
    settings = ads_client.client_settings(env=env, path=tmp_path / "missing.yaml")
    assert "developer_token" not in settings and settings["login_customer_id"] == "1112223333"
    assert ads_client.missing_credentials({"client_id": "a"}) == ["client_secret", "refresh_token"]


def test_the_installed_library_accepts_settings_without_a_developer_token():
    from google.ads.googleads import config as library_config
    from google.ads.googleads.client import GoogleAdsClient
    from google.oauth2.credentials import Credentials

    parsed = library_config.load_from_dict({**OAUTH, "use_proto_plus": True})  # validation only (google-ads >= 32)
    assert "developer_token" not in parsed
    client = GoogleAdsClient(Credentials(token="t"), use_proto_plus=True)  # no token refresh, no request
    assert client.developer_token is None and client.login_customer_id is None
    assert client.get_service("GoogleAdsService")


def test_config_access_level_and_ideas_switch():
    assert make().api.access_level == "explorer" and make().keyword_review.ideas == "auto"
    assert make(**{"keyword_review.ideas": False}).keyword_review.ideas == "off"  # YAML: ideas: off
    with pytest.raises(config.ConfigError, match="api.access_level"):
        make(**{"api.access_level": "gold"})
    with pytest.raises(config.ConfigError, match="keyword_review.ideas"):
        make(**{"keyword_review.ideas": "sometimes"})
    data = {k: v for k, v in EXAMPLE.items() if k != "api"}
    assert config.load_dict(data).api.access_level == "unknown"


def test_quota_status():
    assert doctor.quota_status(make())[0] == "OK"  # explorer: 2,880 a day is enough
    assert "Keyword Planner" in doctor.quota_status(make())[1]
    assert doctor.quota_status(make(**{"api.access_level": "unknown"}))[0] == "PENDING"
    assert doctor.quota_status(make(**{"api.access_level": "test"}))[0] == "PENDING"
    assert doctor.quota_status(make(**{"api.access_level": "basic"}))[0] == "OK"
    assert doctor.quota_status(make(), {"weekly review": 3000})[0] == "WARN"
    assert max(doctor.OPS_ESTIMATE.values()) < config.ACCESS_LEVELS["explorer"]


def test_ideas_skip_reason(use):
    assert "explorer" in keyword_review.ideas_skip_reason()
    assert "off" in keyword_review.ideas_skip_reason(make(**{"keyword_review.ideas": "off", "api.access_level": "basic"}))
    assert keyword_review.ideas_skip_reason(make(**{"api.access_level": "basic"})) is None
    assert keyword_review.ideas_skip_reason(make(**{"api.access_level": "unknown"})) is None
    use(**{"api.access_level": "explorer"})
    assert keyword_review.keyword_ideas(None, None, {1: "US - Search"}, {}) == ([], keyword_review.ideas_skip_reason())


def refused(code=AuthorizationErrorEnum.AuthorizationError.ACTION_NOT_PERMITTED, message="not permitted"):
    error = GoogleAdsError(error_code=ErrorCode(authorization_error=code), message=message)
    return GoogleAdsException(None, None, GoogleAdsFailure(errors=[error]), "request-1")


class Rows:
    """search_stream stub: answers each GAQL query by its FROM clause."""
    def __init__(self, by_from):
        self.by_from = by_from

    def search_stream(self, customer_id, query):
        source = query.split(" FROM ")[1].split()[0]
        return [SimpleNamespace(results=self.by_from.get(source, []))]


def account_rows():
    camp = SimpleNamespace(id=1)
    group = SimpleNamespace(id=11, name="Analytics")
    return {
        "ad_group_criterion": [],
        "keyword_view": [SimpleNamespace(campaign=camp, ad_group=group,
                                         ad_group_criterion=SimpleNamespace(keyword=SimpleNamespace(text="web analytics")))],
        "ad_group_ad": [],
        "campaign_criterion": [],
    }


class Planner:
    def __init__(self, error):
        self.error, self.calls = error, 0

    def generate_keyword_ideas(self, request):
        self.calls += 1
        raise self.error


class Client:
    def __init__(self, planner):
        self.planner = planner

    def get_service(self, name):
        assert name == "KeywordPlanIdeaService"
        return self.planner

    def get_type(self, name):
        assert name == "GenerateKeywordIdeasRequest"
        return GenerateKeywordIdeasRequest()


def test_keyword_ideas_stop_cleanly_when_google_refuses_them(use):
    use(**{"api.access_level": "unknown"})
    rows = account_rows()
    rows["keyword_view"].append(SimpleNamespace(campaign=SimpleNamespace(id=1), ad_group=SimpleNamespace(id=12, name="BI"),
                                                ad_group_criterion=SimpleNamespace(keyword=SimpleNamespace(text="bi tool"))))
    planner = Planner(refused())
    ideas, note = keyword_review.keyword_ideas(Client(planner), Rows(rows), {1: "US - Search"}, {})
    assert ideas == [] and "refused Keyword Planner" in note and "not permitted" in note
    assert planner.calls == 1  # stopped at the first refusal, not once per ad group


def test_keyword_ideas_other_errors_skip_only_that_group(use, capsys):
    use(**{"api.access_level": "basic"})
    error = GoogleAdsException(None, None, GoogleAdsFailure(errors=[GoogleAdsError(message="bad seed")]), "r")
    ideas, note = keyword_review.keyword_ideas(Client(Planner(error)), Rows(account_rows()), {1: "US - Search"}, {})
    assert ideas == [] and note is None
    assert "failed: bad seed" in capsys.readouterr().out


def test_render_shows_the_ideas_note():
    out = {"date": "2026-11-09", "days": 7, "currency": "USD", "negatives": [], "held_winning": [], "positives": [],
           "pauses": [], "ideas": [], "ideas_note": "keyword ideas skipped: keyword_review.ideas is off"}
    assert "NOTE: keyword ideas skipped" in keyword_review.render(out)


def test_refresh_token_is_added_when_the_line_is_missing():
    assert get_refresh_token.with_token("client_id: a\n", "t") == "client_id: a\nrefresh_token: t\n"
    assert get_refresh_token.with_token("refresh_token: INSERT_REFRESH_TOKEN\n", "t") == "refresh_token: t\n"

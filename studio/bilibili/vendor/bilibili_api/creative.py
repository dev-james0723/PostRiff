from . import utils

API = utils.get_api()


def get_own_comments_raw(order: str, pn: int = 1, verify: utils.Verify = None):
    """
    获取自己作品下的评论
    :param order:
    :param pn:
    :param verify:
    :return:
    """
    if verify is None:
        verify = utils.Verify()

    # 参数检查完毕
    params = {
        "order": order,
        "pn": pn
    }
    comment_api = API["creative"]["replies"]
    resp = utils.get(comment_api["url"], params=params, cookies=verify.get_cookies())
    return resp


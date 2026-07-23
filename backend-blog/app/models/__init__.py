"""模型包: 统一导出所有 ORM 模型, 便于建表与导入。"""

# 导出用户模型
from app.models.user import User
# 导出文章模型
from app.models.article import Article
# 导出分类模型
from app.models.category import Category
# 导出标签、文章标签与用户兴趣标签关联模型
from app.models.tag import Tag, ArticleTag, UserTag
# 导出评论模型
from app.models.comment import Comment
# 导出收藏模型
from app.models.favorite import Favorite
# 导出用户文章浏览统计模型
from app.models.browse import UserBrowse

# 显式声明对外可导出的符号
__all__ = [
    "User",
    "Article",
    "Category",
    "Tag",
    "ArticleTag",
    "UserTag",
    "Comment",
    "Favorite",
    "UserBrowse",
]

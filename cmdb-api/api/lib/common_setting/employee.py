# -*- coding:utf-8 -*-

import traceback
from datetime import datetime

from flask import abort
from flask_login import current_user
from sqlalchemy import or_, literal_column, func, not_, and_
from werkzeug.datastructures import MultiDict
from wtforms import Form
from wtforms import IntegerField
from wtforms import StringField
from wtforms import validators

from api.extensions import db
from api.lib.common_setting.acl import ACLManager
from api.lib.common_setting.const import COMMON_SETTING_QUEUE, OperatorType
from api.lib.common_setting.resp_format import ErrFormat
from api.models.common_setting import Employee, Department

acl_user_columns = [
    'email',
    'mobile',
    'nickname',
    'username',
    'password',
    'block',
    'avatar',
]
employee_pop_columns = ['password']
can_not_edit_columns = ['email']


def edit_acl_user(uid, **kwargs):
    user_data = {column: kwargs.get(
        column, '') for column in acl_user_columns if kwargs.get(column, '')}
    if 'block' in kwargs:
        user_data['block'] = kwargs.get('block')
    try:
        acl = ACLManager()
        return acl.edit_user(uid, user_data)
    except Exception as e:
        abort(400, ErrFormat.acl_edit_user_failed.format(str(e)))


def get_block_value(value):
    if value in ['False', 'false', '0', 0]:
        value = False
    else:
        value = True

    return value


def get_employee_list_by_direct_supervisor_id(direct_supervisor_id):
    return Employee.get_by(direct_supervisor_id=direct_supervisor_id)


def get_department_list_by_director_id(director_id):
    return Department.get_by(department_director_id=director_id)


def raise_exception(err):
    raise Exception(err)


def check_department_director_id_or_direct_supervisor_id(_id):
    get_employee_list_by_direct_supervisor_id(
        _id) and raise_exception(ErrFormat.cannot_block_this_employee_is_other_direct_supervisor)
    get_department_list_by_director_id(
        _id) and raise_exception(ErrFormat.cannot_block_this_employee_is_department_manager)


class EmployeeCRUD(object):
    @staticmethod
    def get_employee_by_id(_id):
        return Employee.get_by(
            first=True, to_dict=False, deleted=0, employee_id=_id
        ) or abort(404, ErrFormat.employee_id_not_found.format(_id))

    @staticmethod
    def get_employee_by_uid_with_create(_uid):
        try:
            return EmployeeCRUD.get_employee_by_uid(_uid).to_dict()
        except Exception as e:
            if '不存在' not in str(e):
                abort(400, str(e))

            try:
                acl = ACLManager('acl')
                user_info = acl.get_user_info(_uid)
                return EmployeeCRUD.check_acl_user_and_create(user_info)

            except Exception as e:
                abort(400, str(e))

    @staticmethod
    def get_employee_by_uid(_uid):
        return Employee.get_by(
            first=True, to_dict=False, deleted=0, acl_uid=_uid
        ) or abort(404, ErrFormat.acl_uid_not_found.format(_uid))

    @staticmethod
    def check_acl_user_and_create(user_info):
        existed = Employee.get_by(
            first=True, to_dict=False, username=user_info['username'])
        if existed:
            existed.update(
                acl_uid=user_info['uid'],
            )
            return existed.to_dict()
        if not user_info.get('nickname', None):
            user_info['nickname'] = user_info['name']

        form = EmployeeAddForm(MultiDict(user_info))
        data = form.data
        data['password'] = ''
        data['acl_uid'] = user_info['uid']

        employee = CreateEmployee().create_single(**data)
        return employee.to_dict()

    @staticmethod
    def add(**kwargs):
        try:
            return CreateEmployee().create_single(**kwargs)
        except Exception as e:
            abort(400, str(e))

    @staticmethod
    def update(_id, **kwargs):
        EmployeeCRUD.check_email_unique(kwargs['email'], _id)

        existed = EmployeeCRUD.get_employee_by_id(_id)

        try:
            edit_acl_user(existed.acl_uid, **kwargs)

            for column in employee_pop_columns:
                kwargs.pop(column, None)

            new_department_id = kwargs.get('department_id', None)
            e_list = []
            if new_department_id is not None and new_department_id != existed.department_id:
                e_list = [dict(
                    e_acl_rid=existed.acl_rid,
                    department_id=existed.department_id
                )]

            existed.update(**kwargs)

            if len(e_list) > 0:
                from api.tasks.common_setting import edit_employee_department_in_acl
                edit_employee_department_in_acl.apply_async(
                    args=(e_list, new_department_id, current_user.uid),
                    queue=COMMON_SETTING_QUEUE
                )

            return existed
        except Exception as e:
            return abort(400, str(e))

    @staticmethod
    def edit_employee_by_uid(_uid, **kwargs):
        existed = EmployeeCRUD.get_employee_by_uid(_uid)
        try:
            user = edit_acl_user(_uid, **kwargs)

            for column in employee_pop_columns:
                if kwargs.get(column):
                    kwargs.pop(column)

            return existed.update(**kwargs)
        except Exception as e:
            return abort(400, str(e))

    @staticmethod
    def change_password_by_uid(_uid, password):
        existed = EmployeeCRUD.get_employee_by_uid(_uid)
        try:
            user = edit_acl_user(_uid, password=password)
        except Exception as e:
            return abort(400, str(e))

    @staticmethod
    def get_all_position():
        criterion = [
            Employee.deleted == 0,
        ]
        results = Employee.query.with_entities(
            Employee.position_name
        ).filter(*criterion).group_by(
            Employee.position_name
        ).order_by(
            func.CONVERT(literal_column('position_name using gbk'))
        ).all()

        return [item[0] for item in results if (item[0] is not None and item[0] != '')]

    @staticmethod
    def get_employee_count(block_status):
        criterion = [
            Employee.deleted == 0
        ]

        if block_status >= 0:
            criterion.append(
                Employee.block == block_status
            )

        return Employee.query.filter(
            *criterion
        ).count()

    @staticmethod
    def check_email_unique(email, _id=0):
        criterion = [
            Employee.email == email,
            Employee.deleted == 0,
        ]
        if _id > 0:
            criterion.append(
                Employee.employee_id != _id
            )
        res = Employee.query.filter(
            *criterion
        ).all()

        if res:
            err = ErrFormat.email_already_exists.format(email)
            raise Exception(err)

    @staticmethod
    def get_employee_list_by_body(department_id, block_status, search='', order='', conditions=None, page=1,
                                  page_size=10):
        criterion = [
            Employee.deleted == 0
        ]

        if block_status >= 0:
            criterion.append(
                Employee.block == block_status
            )

        if len(search) > 0:
            search_key = f"%{search}%"
            criterion.append(
                or_(
                    Employee.email.like(search_key),
                    Employee.username.like(search_key),
                    Employee.nickname.like(search_key)
                )
            )

        if department_id > 0:
            from api.lib.common_setting.department import DepartmentCRUD
            department_id_list = DepartmentCRUD.get_department_id_list_by_root(
                department_id)
            criterion.append(
                Employee.department_id.in_(department_id_list)
            )

        if conditions:
            query = EmployeeCRUD.parse_condition_list_to_query(conditions).filter(
                *criterion
            )
        else:
            query = db.session.query(Employee, Department).outerjoin(Department).filter(
                *criterion
            )

        if len(order) > 0:
            query = EmployeeCRUD.format_query_sort(query, order)

        pagination = query.paginate(page=page, per_page=page_size)

        employees = []
        for r in pagination.items:
            d = r.Employee.to_dict()
            d['department_name'] = r.Department.department_name
            employees.append(d)

        return {
            'data_list': employees,
            'page': page,
            'page_size': page_size,
            'total': pagination.total,
        }

    @staticmethod
    def parse_condition_list_to_query(condition_list):
        query = db.session.query(Employee, Department).outerjoin(Department)

        query = EmployeeCRUD.get_query_by_conditions(query, condition_list)
        return query

    @staticmethod
    def get_expr_by_condition(column, operator, value, relation):
        """
        get expr: (and_list, or_list)
        """
        attr = EmployeeCRUD.get_attr_by_column(column)
        # 根据operator生成条件表达式
        if operator == OperatorType.EQUAL:
            expr = [attr == value]
        elif operator == OperatorType.NOT_EQUAL:
            expr = [attr != value]
        elif operator == OperatorType.IN:
            expr = [attr.like('%{}%'.format(value))]
        elif operator == OperatorType.NOT_IN:
            expr = [not_(attr.like('%{}%'.format(value)))]
        elif operator == OperatorType.GREATER_THAN:
            expr = [attr > value]
        elif operator == OperatorType.LESS_THAN:
            expr = [attr < value]
        elif operator == OperatorType.IS_EMPTY:
            if value:
                abort(400, ErrFormat.query_column_none_keep_value_empty.format(column))
            expr = [attr.is_(None)]
            if column not in ["last_login"]:
                expr += [attr == '']
                expr = [or_(*expr)]
        elif operator == OperatorType.IS_NOT_EMPTY:
            if value:
                abort(400, ErrFormat.query_column_none_keep_value_empty.format(column))

            expr = [attr.isnot(None)]
            if column not in ["last_login"]:
                expr += [attr != '']
                expr = [and_(*expr)]
        else:
            abort(400, ErrFormat.not_support_operator.format(operator))

        if relation == "&":
            return expr, []
        elif relation == "|":
            return [], expr
        else:
            return abort(400, ErrFormat.not_support_relation.format(relation))

    @staticmethod
    def check_condition(column, operator, value, relation):
        if column is None or operator is None or relation is None:
            return abort(400, ErrFormat.conditions_field_missing)

        if value and column == "last_login":
            try:
                value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                abort(400, ErrFormat.datetime_format_error.format(column))

    @staticmethod
    def get_attr_by_column(column):
        if 'department' in column:
            attr = Department.__dict__[column]
        else:
            attr = Employee.__dict__[column]
        return attr

    @staticmethod
    def get_query_by_conditions(query, conditions):
        and_list = []
        or_list = []

        for condition in conditions:
            operator = condition.get("operator", None)
            column = condition.get("column", None)
            relation = condition.get("relation", None)
            value = condition.get("value", None)

            EmployeeCRUD.check_condition(column, operator, value, relation)
            a, o = EmployeeCRUD.get_expr_by_condition(
                column, operator, value, relation)
            and_list += a
            or_list += o

        query = query.filter(
            Employee.deleted == 0,
            or_(and_(*and_list), *or_list)
        )

        return query

    @staticmethod
    def get_employee_list_by(department_id, block_status, search='', order='', page=1, page_size=10):
        criterion = [
            Employee.deleted == 0
        ]

        if block_status >= 0:
            criterion.append(
                Employee.block == block_status
            )

        if len(search) > 0:
            search_key = f"%{search}%"
            criterion.append(
                or_(
                    Employee.email.like(search_key),
                    Employee.username.like(search_key),
                    Employee.nickname.like(search_key)
                )
            )

        if department_id > 0:
            from api.lib.common_setting.department import DepartmentCRUD
            department_id_list = DepartmentCRUD.get_department_id_list_by_root(
                department_id)
            criterion.append(
                Employee.department_id.in_(department_id_list)
            )

        query = db.session.query(Employee, Department).outerjoin(Department).filter(
            *criterion
        )

        if len(order) > 0:
            query = EmployeeCRUD.format_query_sort(query, order)

        pagination = query.paginate(page=page, per_page=page_size)
        employees = []
        for r in pagination.items:
            d = r.Employee.to_dict()
            d['department_name'] = r.Department.department_name
            employees.append(d)

        return {
            'data_list': employees,
            'page': page,
            'page_size': page_size,
            'total': pagination.total,
        }

    @staticmethod
    def format_query_sort(query, order):
        order_list = order.split(',')
        all_columns = Employee.get_columns()

        for order_column in order_list:
            if order_column.startswith('-'):
                target_column = order_column[1:]
                if target_column not in all_columns:
                    continue
                query = query.order_by(getattr(Employee, target_column).desc())
            else:
                if order_column not in all_columns:
                    continue

                query = query.order_by(getattr(Employee, order_column).asc())

        return query

    @staticmethod
    def get_employees_by_department_id(department_id, block):
        criterion = [
            Employee.deleted == 0,
            Employee.block == block,
        ]
        if type(department_id) == list:
            if len(department_id) == 0:
                return []
            else:
                criterion.append(
                    Employee.department_id.in_(department_id)
                )
        else:
            criterion.append(
                Employee.department_id == department_id
            )

        results = Employee.query.filter(
            *criterion
        ).all()

        return [r.to_dict() for r in results]

    @staticmethod
    def get_employee_notice_by_ids(employee_ids):
        criterion = [
            Employee.employee_id.in_(employee_ids),
            Employee.deleted == 0,
        ]
        direct_columns = ['email', 'mobile']
        employees = Employee.query.filter(
            *criterion
        ).all()
        results = []
        for employee in employees:
            d = employee.to_dict()
            tmp = dict(
                employee_id=employee.employee_id,
            )
            for column in direct_columns:
                tmp[column] = d.get(column, '')
            notice_info = d.get('notice_info', {})
            tmp.update(**notice_info)
            results.append(tmp)
        return results


def get_user_map(key='uid', acl=None):
    """
    {
        uid: userinfo
    }
    """
    if acl is None:
        acl = ACLManager()
    data = {user[key]: user for user in acl.get_all_users()}

    return data


def format_params(params):
    for k in ['_key', '_secret']:
        params.pop(k, None)
    return params


class CreateEmployee(object):
    def __init__(self):
        self.acl = ACLManager()
        self.all_acl_users = self.acl.get_all_users()

    def check_acl_user(self, user_data):
        target_email = list(filter(lambda x: x['email'] == user_data['email'], self.all_acl_users))
        if target_email:
            return target_email[0]

        target_username = list(filter(lambda x: x['username'] == user_data['username'], self.all_acl_users))
        if target_username:
            return target_username[0]

    def add_acl_user(self, **kwargs):
        user_data = {column: kwargs.get(
            column, '') for column in acl_user_columns if kwargs.get(column, '')}
        try:
            existed = self.check_acl_user(user_data)
            if not existed:
                return self.acl.create_user(user_data)
            return existed
        except Exception as e:
            abort(400, ErrFormat.acl_add_user_failed.format(str(e)))

    def create_single(self, **kwargs):
        EmployeeCRUD.check_email_unique(kwargs['email'])
        user = self.add_acl_user(**kwargs)
        kwargs['acl_uid'] = user['uid']
        kwargs['last_login'] = user['last_login']

        for column in employee_pop_columns:
            kwargs.pop(column)

        return Employee.create(
            **kwargs
        )

    def create_single_with_import(self, **kwargs):
        user = self.add_acl_user(**kwargs)
        kwargs['acl_uid'] = user['uid']
        kwargs['last_login'] = user['last_login']

        for column in employee_pop_columns:
            kwargs.pop(column)

        existed = Employee.get_by(
            first=True, to_dict=False, deleted=0, acl_uid=user['uid']
        )
        if existed:
            return existed

        return Employee.create(
            **kwargs
        )

    def get_department_by_name(self, d_name):
        return Department.get_by(first=True, department_name=d_name)

    def get_end_department_id(self, department_name_list, department_name_map):
        parent_id = 0

        end_d_id = 0
        for d_name in department_name_list:
            tmp_d = self.get_department_by_name(d_name)
            if not tmp_d:
                tmp_d = Department.create(
                    department_name=d_name, department_parent_id=parent_id).to_dict()
            else:
                if tmp_d['department_parent_id'] != parent_id:
                    department_name_map[d_name] = tmp_d
                    raise Exception(ErrFormat.department_level_relation_error)

            department_name_map[d_name] = tmp_d

            end_d_id = tmp_d['department_id']
            parent_id = tmp_d['department_id']

        return end_d_id

    def format_department_id(self, employee):
        department_name_map = {}
        try:
            department_name = employee.get('department_name', '')
            if len(department_name) == 0:
                return employee
            department_name_list = department_name.split('/')
            employee['department_id'] = self.get_end_department_id(
                department_name_list, department_name_map)

        except Exception as e:
            employee['err'] = str(e)

        return employee

    def batch_create(self, employee_list):
        err_list = []

        for employee in employee_list:
            try:
                username = employee.get('username', None)
                if username is None:
                    employee['username'] = employee['email']

                employee = self.format_department_id(employee)
                err = employee.get('err', None)
                if err:
                    raise Exception(err)

                params = format_params(employee)
                form = EmployeeAddForm(MultiDict(params))
                if not form.validate():
                    raise Exception(
                        ','.join(['{}: {}'.format(filed, ','.join(msg)) for filed, msg in form.errors.items()]))

                self.create_single_with_import(**form.data)
            except Exception as e:
                err_list.append({
                    'email': employee.get('email', ''),
                    'nickname': employee.get('nickname', ''),
                    'err': str(e),
                })
                traceback.print_exc()

        return err_list


class EmployeeAddForm(Form):
    username = StringField(validators=[
        validators.DataRequired(message=ErrFormat.username_is_required),
        validators.Length(max=255),
    ])
    email = StringField(validators=[
        validators.DataRequired(message=ErrFormat.email_is_required),
        validators.Email(message=ErrFormat.email_format_error),
        validators.Length(max=255),
    ])
    password = StringField(validators=[
        validators.Length(max=255),
    ])
    position_name = StringField(validators=[])

    nickname = StringField(validators=[
        validators.DataRequired(message=ErrFormat.nickname_is_required),
        validators.Length(max=255),
    ])
    sex = StringField(validators=[])
    mobile = StringField(validators=[])
    department_id = IntegerField(validators=[], default=0)
    direct_supervisor_id = IntegerField(validators=[], default=0)


class EmployeeUpdateByUidForm(Form):
    nickname = StringField(validators=[
        validators.DataRequired(message=ErrFormat.nickname_is_required),
        validators.Length(max=255),
    ])
    avatar = StringField(validators=[])
    sex = StringField(validators=[])
    mobile = StringField(validators=[])

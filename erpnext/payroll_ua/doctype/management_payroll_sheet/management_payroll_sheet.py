"""Нарахування управлінської зарплати за місяць — готівкова половина.

Рахується тим самим кодом і по тому самому табелю, що й офіційне нарахування
(`erpnext.payroll_ua.payroll_sheet_base`), але платить лише готівкову частину — з каси, за
домовленістю 5-6-го числа. Нарахування в HRMS цієї половини не стосується: офіційно вона не
проходить, тож ані Payroll Entry, ані листка тут немає.
"""

from erpnext.payroll_ua.payroll_sheet_base import CASH, PayrollSheetBase


class ManagementPayrollSheet(PayrollSheetBase):
	part = CASH

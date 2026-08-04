from __future__ import annotations

import streamlit as st

from core.auth import has_permission
from core.csv_import import dataframe_to_excel_bytes, save_follower_overrides
from core.i18n import tr
from core.style import hero
from screens._shared import filtered_results_ui


def page_report(user: dict) -> None:
    if not has_permission(user, "view_reports"):
        st.error(tr("You do not have permission to view reports.", "У вас нет прав для просмотра отчетов."))
        return
    hero(
        "Reports",
        tr(
            "Final table after matching Meta and PR. You can manually refine ad account follower counts for selected rows.",
            "Финальная таблица после матчинга Meta + PR. Для выбранных строк можно вручную уточнить подписчиков из рекламного кабинета.",
        ),
        ["Meta followers - PR followers", "Manual PR override", "Export CSV / Excel"],
    )
    f = filtered_results_ui()
    if f.empty:
        st.info(tr("No final data yet, or the filters returned nothing.", "Пока нет финальных данных или фильтры ничего не нашли."))
        return

    total_followers = int(f["final_followers"].sum())
    total_spend = float(f["spend_usd"].sum())
    total_pr = int(f["pr_followers"].sum())
    cpf = total_spend / total_pr if total_pr > 0 else None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{len(f):,}")
    c2.metric("Final followers", f"{total_followers:,}")
    c3.metric("Spend", f"${total_spend:,.2f}")
    c4.metric("CPF", "—" if cpf is None else f"${cpf:,.2f}")

    if has_permission(user, "edit_reports"):
        st.markdown("### " + tr("Manual Ad Account Follower Adjustment", "Ручное уточнение подписчиков из рекламного кабинета"))
        st.caption(
            tr(
                "Select the rows you need first. They will appear in a separate block above where you can enter the actual PR follower count. "
                "Rows with warnings are selected automatically. Clear the manual field and save the row to return to the CSV value.",
                "Сначала отметьте нужные строки. Они появятся в отдельном блоке сверху, где можно указать фактическое число подписчиков PR. "
                "Строки с предупреждением выбраны автоматически. "
                "Чтобы вернуть значение из CSV, очистите ручное поле и сохраните строку.",
            )
        )
        selection_cols = [
            "Выбрать", "account", "publication_date", "publication_id", "publication_link",
            "post_reach", "meta_followers", "pr_followers", "final_followers", "warning", "period_start", "period_end",
        ]
        selection_data = f.copy()
        selection_data.insert(0, "Выбрать", selection_data["warning"].fillna("") != "")
        selected_rows_container = st.container()

        st.markdown("#### " + tr("All Rows", "Все строки"))
        selected_rows = st.data_editor(
            selection_data[selection_cols],
            use_container_width=True,
            hide_index=True,
            disabled=[c for c in selection_cols if c != "Выбрать"],
            column_config={
                "Выбрать": st.column_config.CheckboxColumn(tr("Select", "Выбрать"), help=tr("Add row to the manual input block", "Добавить строку в блок ручного ввода")),
                "account": tr("Account", "Аккаунт"),
                "publication_date": tr("Publication date", "Дата публикации"),
                "publication_id": tr("Publication ID", "ID публикации"),
                "publication_link": st.column_config.LinkColumn(tr("Link", "Ссылка")),
                "post_reach": tr("Post reach", "Охват поста"),
                "meta_followers": tr("Meta followers", "Подписчики Meta"),
                "pr_followers": tr("PR for calculation", "PR для расчёта"),
                "final_followers": tr("Final followers", "Итог подписчиков"),
                "warning": tr("Comment", "Комментарий"),
                "period_start": None,
                "period_end": None,
            },
            key="followers_override_selector",
        )
        selected_rows = selected_rows[selected_rows["Выбрать"] == True].copy()  # noqa: E712

        with selected_rows_container:
            st.markdown("#### " + tr("Selected Rows For Manual Input", "Выбранные строки для ручного ввода"))
            if selected_rows.empty:
                st.info(tr("Select rows in the list below. Rows with warnings are selected automatically.", "Отметьте строки в списке ниже. Строки с предупреждением отмечаются автоматически."))
            else:
                selected_keys = ["account", "period_start", "period_end", "publication_id"]
                selected_source = f.merge(selected_rows[selected_keys], on=selected_keys, how="inner")
                selected_editor_cols = [
                    "account", "publication_date", "publication_id", "publication_link",
                    "post_reach", "meta_followers", "imported_pr_followers", "manual_pr_followers", "pr_followers",
                    "final_followers", "warning", "period_start", "period_end",
                ]
                edited = st.data_editor(
                    selected_source[selected_editor_cols],
                    use_container_width=True,
                    hide_index=True,
                    disabled=[c for c in selected_editor_cols if c != "manual_pr_followers"],
                    column_config={
                        "account": tr("Account", "Аккаунт"),
                        "publication_date": tr("Publication date", "Дата публикации"),
                        "publication_id": tr("Publication ID", "ID публикации"),
                        "publication_link": st.column_config.LinkColumn(tr("Link", "Ссылка")),
                        "post_reach": tr("Post reach", "Охват поста"),
                        "meta_followers": tr("Meta followers", "Подписчики Meta"),
                        "imported_pr_followers": tr("PR from CSV", "PR из CSV"),
                        "manual_pr_followers": st.column_config.NumberColumn(
                            tr("Manual PR", "PR вручную"), min_value=0, step=1, format="%d",
                            help=tr("Empty means use the CSV value", "Пусто — использовать значение из CSV"),
                        ),
                        "pr_followers": tr("PR for calculation", "PR для расчёта"),
                        "final_followers": tr("Final followers", "Итог подписчиков"),
                        "warning": tr("Comment", "Комментарий"),
                        "period_start": None,
                        "period_end": None,
                    },
                    key="followers_override_editor",
                )
                if st.button(tr("Save manual values and recalculate", "Сохранить ручные значения и пересчитать"), type="primary", use_container_width=True):
                    try:
                        edited.insert(0, "Изменить", True)
                        changed = save_follower_overrides(edited, user)
                        st.success(tr(f"Saved rows: {changed}. The report was recalculated.", f"Сохранено строк: {changed}. Отчет пересчитан."))
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
    else:
        st.info(tr("View-only mode: your role cannot edit manual values.", "Режим просмотра: ваша роль не позволяет менять ручные значения."))

    st.markdown("### " + tr("Final Report", "Финальный отчет"))
    display_cols = [
        "account", "month", "publication_date", "publication_id", "publication_link",
        "post_reach", "meta_followers", "pr_followers", "final_followers", "spend_usd", "cpf_usd",
        "meta_uploaded_by", "pr_uploaded_by", "override_updated_by", "updated_at",
    ]
    final_report = f[display_cols]
    st.dataframe(
        final_report,
        use_container_width=True,
        hide_index=True,
        column_config={
            "publication_link": st.column_config.LinkColumn(tr("Publication link", "Ссылка на публикацию")),
            "account": tr("Account", "Аккаунт"),
            "month": tr("Month", "Месяц"),
            "publication_date": tr("Publication date", "Дата публикации"),
            "publication_id": tr("Publication ID", "ID публикации"),
            "post_reach": tr("Post reach", "Охват поста"),
            "meta_followers": tr("Meta followers", "Подписчики Meta"),
            "pr_followers": tr("PR followers for calculation", "Подписчики PR для расчёта"),
            "final_followers": tr("Final followers", "Итог подписчиков"),
            "spend_usd": st.column_config.NumberColumn("Spend, USD", format="$%.2f"),
            "cpf_usd": st.column_config.NumberColumn("CPF, USD", format="$%.2f"),
            "meta_uploaded_by": tr("Meta uploaded by", "Meta загрузил"),
            "pr_uploaded_by": tr("PR uploaded by", "PR загрузил"),
            "override_updated_by": tr("Manual value updated by", "Ручное значение обновил"),
            "updated_at": tr("Updated at", "Обновлено"),
        },
    )
    csv_col, excel_col = st.columns(2)
    csv_col.download_button(
        tr("Download report CSV", "Скачать отчет CSV"),
        data=final_report.to_csv(index=False).encode("utf-8-sig"),
        file_name="instagram_followers_report.csv",
        mime="text/csv",
        use_container_width=True,
    )
    excel_col.download_button(
        tr("Download report Excel", "Скачать отчет Excel"),
        data=dataframe_to_excel_bytes(final_report),
        file_name="instagram_followers_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

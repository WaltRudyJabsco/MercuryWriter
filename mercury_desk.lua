-- A writing surface over ordinary Neovim buffers: no plugins or user config.
local api = vim.api
local session = vim.json.decode(table.concat(vim.fn.readfile(vim.env.MERCURY_SESSION), '\n'))
local panes = {}
local current_pane = 1
vim.g.mapleader = ' '
vim.o.hidden = true
vim.o.swapfile = false
vim.o.backup = false
vim.o.writebackup = false
vim.o.undofile = false
vim.o.laststatus = 2
vim.o.showmode = true
vim.o.mouse = 'a'
vim.o.splitbelow = true
vim.o.splitright = false
vim.o.termguicolors = true
vim.cmd('highlight Normal guibg=#1b1b1b guifg=#e8e4dc')
vim.cmd('highlight StatusLine guibg=#342f24 guifg=#f6e1a9')

local function writing_options(win)
  vim.wo[win].wrap = true
  vim.wo[win].linebreak = true
  vim.wo[win].number = false
  vim.wo[win].signcolumn = 'no'
  vim.wo[win].spell = true
  vim.wo[win].statusline = " Mercury · %t %m %{get(g:,'mercury_save_status','Local checkpoint')} %= %l:%c · :MercurySplit · Tab manuscript "
end

local function choose(pane, index)
  local scene = session.scenes[index]
  if not scene then return end
  pane.index = index
  api.nvim_set_current_win(pane.editor)
  vim.cmd('edit ' .. vim.fn.fnameescape(scene.path))
  vim.bo.filetype = 'markdown'
  writing_options(pane.editor)
end

local function make_pane(editor, index)
  local pane = {editor=editor, index=index}
  writing_options(editor)
  vim.cmd('leftabove vertical 26split')
  pane.navigator = api.nvim_get_current_win()
  pane.buffer = api.nvim_create_buf(false, true)
  api.nvim_win_set_buf(pane.navigator, pane.buffer)
  local labels = {}
  for _, scene in ipairs(session.scenes) do
    table.insert(labels, string.format('%d.%d %s', scene.chapter_index+1, scene.scene_index+1, scene.scene_title))
  end
  api.nvim_buf_set_lines(pane.buffer,0,-1,false,labels)
  vim.bo[pane.buffer].modifiable = false
  vim.bo[pane.buffer].bufhidden = 'hide'
  vim.wo[pane.navigator].wrap = false
  vim.wo[pane.navigator].number = false
  vim.wo[pane.navigator].winfixwidth = true
  vim.wo[pane.navigator].cursorline = true
  vim.wo[pane.navigator].statusline = ' Manuscript · Enter scene '
  vim.keymap.set('n','<CR>',function() choose(pane,api.nvim_win_get_cursor(pane.navigator)[1]) end,{buffer=pane.buffer})
  vim.keymap.set('n','<Tab>',function() api.nvim_set_current_win(pane.editor) end,{buffer=pane.buffer})
  choose(pane,index)
  return pane
end

panes[1] = make_pane(api.nvim_get_current_win(),session.initial or 1)
local function split()
  if #panes > 1 then
    local second = table.remove(panes)
    if api.nvim_win_is_valid(second.navigator) then api.nvim_win_close(second.navigator,true) end
    if api.nvim_win_is_valid(second.editor) then api.nvim_win_close(second.editor,true) end
    current_pane=1;api.nvim_set_current_win(panes[1].editor)
    return
  end
  api.nvim_set_current_win(panes[1].editor)
  -- Split the row containing both navigator and manuscript.
  vim.cmd('botright split')
  panes[2]=make_pane(api.nvim_get_current_win(),panes[1].index)
  current_pane=2
  vim.cmd('wincmd =')
end

api.nvim_create_user_command('MercurySplit',split,{desc='Toggle two Mercury writing rows'})
api.nvim_create_user_command('MercuryManuscript',function()
  api.nvim_set_current_win(panes[current_pane].navigator)
end,{})
api.nvim_create_autocmd('WinEnter',{callback=function()
  local win=api.nvim_get_current_win()
  for index,pane in ipairs(panes) do
    if win==pane.editor or win==pane.navigator then current_pane=index end
  end
end})
vim.keymap.set('n','<Tab>',function()
  local pane=panes[current_pane]
  api.nvim_set_current_win(api.nvim_get_current_win()==pane.navigator and pane.editor or pane.navigator)
end)
vim.keymap.set('n','<leader>s',split)
vim.keymap.set({'n','i'},'<C-s>',function() vim.cmd('write') end)
vim.keymap.set('n','<leader>q',function() vim.cmd('wall');vim.cmd('qa') end)
if session.split then split() end

local receipt_path = vim.fn.fnamemodify(vim.env.MERCURY_SESSION,':h') .. '/session.json'
local timer = (vim.uv or vim.loop).new_timer()
local last_error = ''
timer:start(1000,1000,vim.schedule_wrap(function()
  local ok,receipt=pcall(function() return vim.json.decode(table.concat(vim.fn.readfile(receipt_path),'\n')) end)
  if not ok then return end
  local error=receipt.error or ''
  vim.g.mercury_save_status = error~='' and 'SAVE NEEDS ATTENTION · local files retained' or 'Mercury revision ' .. string.sub(receipt.base_revision or '',1,16)
  if error~='' and error~=last_error then vim.notify(error .. '\nLocal recovery: ' .. receipt_path,vim.log.levels.WARN) end
  last_error=error
  vim.cmd('redrawstatus')
end))
api.nvim_create_autocmd('VimLeavePre',{once=true,callback=function() timer:stop();timer:close() end})
